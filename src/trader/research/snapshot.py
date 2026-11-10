"""Live market snapshot judged against history: what happened after similar states.

Research only (ADR-029). Reads public Kraken candles and order books and local history CSVs;
it never trades and is never imported by the trading pipeline. Network access goes through
injectable fetchers so tests run offline.

Method: measure today's state per coin (trailing 1/3/12-month returns, 4h RSI, trend side,
volatility percentile, squeeze percentile, order-book depth). Then find every past 4h bar in
that coin's history with the same state, keep non-overlapping episodes (one per horizon), and
report what a long position earned over the next week and month, with a bootstrap 90% range.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from trader.research.lab import load_csv, rsi

# Reason: a fixed allowlist; no option can make this module query an arbitrary pair.
PAIRS = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD", "SUI": "SUIUSD"}
MONTH = 180  # 30 days of 4h bars
HORIZONS = {"1 week": 42, "1 month": 180}
MIN_EPISODES = 5
KRAKEN = "https://api.kraken.com/0/public"

OhlcFetcher = Callable[[str, int], pd.DataFrame]
BookFetcher = Callable[[str], tuple[np.ndarray, np.ndarray]]


def _get(path: str, params: dict[str, str | int]) -> dict:  # type: ignore[type-arg]
    url = f"{KRAKEN}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (fixed https URL)
        body = json.loads(resp.read())
    if body.get("error"):
        raise ValueError(f"kraken: {body['error']}")
    return body["result"]  # type: ignore[no-any-return]


def kraken_ohlc(pair: str, minutes: int) -> pd.DataFrame:
    """
    Closed public Kraken candles (the still-forming last candle is dropped).

    Args:
        pair (str): Kraken pair, e.g. ``XBTUSD``.
        minutes (int): 240 or 1440.

    Returns:
        pd.DataFrame: UTC-indexed float OHLCV, oldest first.
    """
    res = _get("OHLC", {"pair": pair, "interval": minutes})
    rows = next(v for k, v in res.items() if k != "last")
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "vwap", "volume", "n"])
    df.index = pd.to_datetime(df.pop("t").astype(int), unit="s", utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype(float).iloc[:-1]


def kraken_book(pair: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Public order book, up to 500 levels a side.

    Args:
        pair (str): Kraken pair.

    Returns:
        tuple[np.ndarray, np.ndarray]: bids and asks as ``[[price, qty], ...]``, best first.
    """
    side = next(iter(_get("Depth", {"pair": pair, "count": 500}).values()))
    bids = np.array([[float(p), float(q)] for p, q, *_ in side["bids"]])
    asks = np.array([[float(p), float(q)] for p, q, *_ in side["asks"]])
    return bids, asks


@dataclass(frozen=True)
class State:
    """Today's measurable state for one coin."""

    price: float
    m1: float
    m3: float
    m12: float
    rsi_4h: float
    above_sma200_4h: bool
    vol30_pct_of_year: float
    squeeze_pct: float  # 42-bar range width percentile over 300 bars; low = quiet
    spread_bps: float
    bid_usd_within_1pct: float
    ask_usd_within_1pct: float
    last_bar_utc: str


def rsi_bucket(x: float) -> str:
    """Oversold below 30, overbought above 70, else neutral."""
    return "oversold" if x < 30 else "overbought" if x > 70 else "neutral"


def momentum_pattern(m1: float, m3: float, m12: float) -> str:
    """Signs of the 1/3/12-month returns, e.g. ``12m down, 3m up, 1m down``."""
    return f"12m {_dir(m12)}, 3m {_dir(m3)}, 1m {_dir(m1)}"


def _dir(x: float) -> str:
    return "up" if x > 0 else "down"


def book_depth(bids: np.ndarray, asks: np.ndarray) -> tuple[float, float, float]:
    """
    Spread and the dollar depth within 1% of the mid price.

    Args:
        bids (np.ndarray): ``[[price, qty], ...]`` best first.
        asks (np.ndarray): Same for asks.

    Returns:
        tuple[float, float, float]: spread in bps, bid dollars, ask dollars.

    Raises:
        ValueError: If either side is empty.
    """
    if len(bids) == 0 or len(asks) == 0:
        raise ValueError("empty order book")
    mid = (bids[0, 0] + asks[0, 0]) / 2
    b = bids[bids[:, 0] >= mid * 0.99]
    a = asks[asks[:, 0] <= mid * 1.01]
    return (
        float((asks[0, 0] - bids[0, 0]) / mid * 1e4),
        float((b[:, 0] * b[:, 1]).sum()),
        float((a[:, 0] * a[:, 1]).sum()),
    )


def live_state(h4: pd.DataFrame, d1: pd.DataFrame, bids: np.ndarray, asks: np.ndarray) -> State:
    """
    Measure one coin's state from closed 4h and daily candles and the order book.

    Args:
        h4 (pd.DataFrame): Closed 4h candles (at least 300).
        d1 (pd.DataFrame): Closed daily candles (more than 365 for a 12-month return).
        bids (np.ndarray): Order book bids.
        asks (np.ndarray): Order book asks.

    Returns:
        State: The coin's state.

    Raises:
        ValueError: If there is too little data.
    """
    if len(h4) < 300 or len(d1) <= 365:
        raise ValueError("need >= 300 4h candles and > 365 daily candles")
    c4, cd = h4["close"], d1["close"]
    lr = np.log(cd).diff()
    vol = lr.rolling(30).std().dropna()
    width = (h4["high"].rolling(42).max() - h4["low"].rolling(42).min()) / c4
    spread, bid1, ask1 = book_depth(bids, asks)
    return State(
        price=float(c4.iloc[-1]),
        m1=_ret(cd, 30),
        m3=_ret(cd, 90),
        m12=_ret(cd, 365),
        rsi_4h=float(rsi(c4, 14).iloc[-1]),
        above_sma200_4h=bool(c4.iloc[-1] > c4.rolling(200).mean().iloc[-1]),
        vol30_pct_of_year=float((vol.iloc[-365:] <= vol.iloc[-1]).mean()),
        squeeze_pct=float((width.iloc[-300:] <= width.iloc[-1]).mean()),
        spread_bps=spread,
        bid_usd_within_1pct=bid1,
        ask_usd_within_1pct=ask1,
        last_bar_utc=h4.index[-1].isoformat(),
    )


def _ret(close: pd.Series, n: int) -> float:
    """Return over the last ``n`` candles."""
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1)


def episodes(mask: np.ndarray, h: int) -> np.ndarray:
    """
    Non-overlapping sample of qualifying bars: take one, then skip the next ``h`` bars.

    Args:
        mask (np.ndarray): Boolean per bar.
        h (int): Horizon in bars.

    Returns:
        np.ndarray: Selected bar indices.
    """
    out, nxt = [], -1
    for i in np.flatnonzero(mask):
        if i >= nxt:
            out.append(int(i))
            nxt = int(i) + h
    return np.array(out, dtype=int)


@dataclass(frozen=True)
class Analog:
    """What a long position earned after past bars that matched a condition."""

    condition: str
    horizon: str
    episodes: int
    mean: float | None = None
    median: float | None = None
    up_share: float | None = None
    range90: tuple[float, float] | None = None


def analogs(hist: pd.DataFrame, state: State, seed: int = 7) -> list[Analog]:
    """
    Forward returns after past bars matching today's state, per condition and horizon.

    Conditions, from broad to narrow: the whole history (baseline); the same 1/3/12-month
    momentum pattern; that pattern plus the same RSI bucket; that pattern plus the same side
    of the 200-bar average. A long position enters at the next bar's open.

    Args:
        hist (pd.DataFrame): The coin's 4h history.
        state (State): Today's state.
        seed (int): Bootstrap seed (fixed for reproducible output).

    Returns:
        list[Analog]: One row per condition and horizon.
    """
    rng = np.random.default_rng(seed)
    c = hist["close"]
    m1, m3, m12 = c.pct_change(MONTH), c.pct_change(3 * MONTH), c.pct_change(12 * MONTH)
    same = (np.sign(m1) == np.sign(state.m1)) & (np.sign(m3) == np.sign(state.m3))
    same &= np.sign(m12) == np.sign(state.m12)
    r = rsi(c, 14)
    bucket = r.map(lambda x: rsi_bucket(x) if not math.isnan(x) else "")
    above = c > c.rolling(200).mean()
    conds = {
        "all history (baseline)": m12.notna(),
        "same momentum pattern": same,
        f"same pattern + RSI {rsi_bucket(state.rsi_4h)}": same
        & (bucket == rsi_bucket(state.rsi_4h)),
        f"same pattern + {'above' if state.above_sma200_4h else 'below'} 200-bar average": same
        & (above == state.above_sma200_4h),
    }
    out: list[Analog] = []
    for hname, h in HORIZONS.items():
        fwd = (c.shift(-h) / hist["open"].shift(-1) - 1).to_numpy(dtype=float)
        for name, cond in conds.items():
            idx = episodes(cond.fillna(False).to_numpy(dtype=bool) & ~np.isnan(fwd), h)
            x = fwd[idx]
            if len(x) < MIN_EPISODES:
                out.append(Analog(name, hname, len(x)))
                continue
            boots = rng.choice(x, size=(2000, len(x))).mean(axis=1)
            lo, hi = np.percentile(boots, [5, 95])
            out.append(
                Analog(
                    name,
                    hname,
                    len(x),
                    float(x.mean()),
                    float(np.median(x)),
                    float((x > 0).mean()),
                    (float(lo), float(hi)),
                )
            )
    return out


@dataclass
class Snapshot:
    """One run: states, history comparisons, and cross-coin correlation."""

    as_of_utc: str
    capital: float
    states: dict[str, State] = field(default_factory=dict)
    analogs: dict[str, list[Analog]] = field(default_factory=dict)
    history_span: dict[str, str] = field(default_factory=dict)
    correlation: dict[str, dict[str, float]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize for ``snapshot.json``."""
        return json.dumps(asdict(self), indent=1, default=str)


def take_snapshot(
    history_dir: Path,
    capital: float = 2500.0,
    fetch_ohlc: OhlcFetcher = kraken_ohlc,
    fetch_book: BookFetcher = kraken_book,
    now: datetime | None = None,
) -> Snapshot:
    """
    Measure every coin live and compare with its history when a history CSV exists.

    A coin whose live data fails is recorded in ``errors`` and skipped; the others still run.

    Args:
        history_dir (Path): Folder with ``<coin>_usd_4h.csv`` files (any subset).
        capital (float): Dollars used to express results.
        fetch_ohlc (OhlcFetcher): Candle fetcher (injectable for tests).
        fetch_book (BookFetcher): Order-book fetcher (injectable for tests).
        now (datetime | None): Clock override for tests.

    Returns:
        Snapshot: The result.
    """
    snap = Snapshot((now or datetime.now(UTC)).isoformat(timespec="minutes"), capital)
    returns: dict[str, pd.Series] = {}
    for coin, pair in PAIRS.items():
        try:
            h4, d1 = fetch_ohlc(pair, 240), fetch_ohlc(pair, 1440)
            bids, asks = fetch_book(pair)
            snap.states[coin] = live_state(h4, d1, bids, asks)
        except (OSError, ValueError, KeyError, StopIteration) as exc:
            snap.errors[coin] = str(exc) or type(exc).__name__
            continue
        returns[coin] = np.log(h4["close"]).diff().iloc[-180:]
        path = history_dir / f"{coin.lower()}_usd_4h.csv"
        if path.exists():
            hist = load_csv(str(path))
            snap.history_span[coin] = f"{hist.index[0].date()} to {hist.index[-1].date()}"
            snap.analogs[coin] = analogs(hist, snap.states[coin])
    if len(returns) > 1:
        corr = pd.DataFrame(returns).corr().round(2)
        snap.correlation = {
            str(k): {str(j): float(v) for j, v in row.items()} for k, row in corr.iterrows()
        }
    return snap


def _price(x: float) -> str:
    return f"${x:,.2f}" if x >= 1 else f"${x:,.4f}"


def _usd(x: float) -> str:
    return f"-${-x:,.0f}" if x < 0 else f"+${x:,.0f}"


def render_markdown(snap: Snapshot) -> str:
    """
    Plain-language report: live state, then "what happened next" in dollars.

    Args:
        snap (Snapshot): A snapshot.

    Returns:
        str: Markdown.
    """
    cap = snap.capital
    lines = [
        f"# Market snapshot {snap.as_of_utc} UTC",
        "",
        "Research only: past outcomes after similar states, not a forecast. Results are not"
        " guaranteed.",
        "",
        "## Now (Kraken public data)",
        "",
        "| Coin | Price | 1 month | 3 months | 12 months | RSI 4h | 200-bar avg | Volatility"
        " (pct of year) | Squeeze (pct) | Spread | Depth within 1% (bid / ask) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for coin, s in snap.states.items():
        side = "above" if s.above_sma200_4h else "below"
        quiet = " (quiet)" if s.squeeze_pct <= 0.25 else ""
        depth = f"${s.bid_usd_within_1pct / 1e6:,.1f}M / ${s.ask_usd_within_1pct / 1e6:,.1f}M"
        lines.append(
            f"| {coin} | {_price(s.price)} | {s.m1:+.0%} | {s.m3:+.0%} | {s.m12:+.0%} |"
            f" {s.rsi_4h:.0f} ({rsi_bucket(s.rsi_4h)}) | {side} | {s.vol30_pct_of_year:.0%}"
            f" | {s.squeeze_pct:.0%}{quiet} | {s.spread_bps:.2f} bps | {depth} |"
        )
    for coin, err in snap.errors.items():
        lines.append(f"| {coin} | live data unavailable: {err} |")
    if snap.correlation:
        vals = [v for k, row in snap.correlation.items() for j, v in row.items() if j > k]
        lines += [
            "",
            f"30-day correlation between coins: {min(vals):.2f} to {max(vals):.2f}"
            + (
                " (they move almost as one: holding several is close to one bet)"
                if min(vals) >= 0.8
                else ""
            ),
        ]
    lines += ["", f"## What happened next in the past (long position, ${cap:,.0f})", ""]
    for coin, rows in snap.analogs.items():
        s = snap.states[coin]
        lines += [
            f"**{coin}**: today's pattern is *{momentum_pattern(s.m1, s.m3, s.m12)}*;"
            f" history {snap.history_span[coin]}."
            " A short earns roughly the opposite, before costs.",
            "",
            "| Condition | Horizon | Times seen | Average | Rose | 90% range of the average |",
            "|---|---|---|---|---|---|",
        ]
        for a in rows:
            if a.mean is None or a.range90 is None or a.up_share is None:
                lines.append(
                    f"| {a.condition} | {a.horizon} | {a.episodes} | too few to judge | | |"
                )
                continue
            lo, hi = a.range90
            note = " (excludes $0)" if lo > 0 or hi < 0 else ""
            avg = f"{_usd(a.mean * cap)} ({a.mean:+.1%})"
            lines.append(
                f"| {a.condition} | {a.horizon} | {a.episodes} | {avg} | {a.up_share:.0%} |"
                f" {_usd(lo * cap)} to {_usd(hi * cap)}{note} |"
            )
        lines.append("")
    n = sum(len(rows) for rows in snap.analogs.values())
    hits = sum(
        1
        for rows in snap.analogs.values()
        for a in rows
        if a.range90 and (a.range90[0] > 0 or a.range90[1] < 0)
    )
    if n:
        # Reason: a 90% range excludes $0 about 10% of the time by luck alone, so with many
        # comparisons some "excludes $0" rows are expected even when nothing is there.
        lines.append(
            f"Of {n} comparisons, {hits} have a range that excludes $0; about {n / 10:.0f} would"
            " by luck alone. Treat a single such row as a lead to watch, not a finding."
        )
        lines.append("")
    missing = [c for c in snap.states if c not in snap.analogs]
    if missing:
        lines.append(
            f"No local history for {', '.join(missing)}: fetch it with"
            " `scripts/fetch_coinbase_history.py` to compare with the past."
        )
    return "\n".join(lines) + "\n"
