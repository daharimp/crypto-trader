"""Data the dashboard shows, built from saved state and public data (ADR-026).

Every function here is read-only. Market data comes through an injectable candle fetcher so
tests never touch the network.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trader.features.pipeline import sma
from trader.perps.backtest import Bar, run_perps_backtest
from trader.perps.params import PerpsConfigUnresolvedError, PerpsParams

# Reason: chart markets are fixed (the trading universe); a query parameter can never pick
# an arbitrary symbol.
MARKETS = {
    "BTC": "BTC/USD",
    "ETH": "ETH/USD",
    "SOL": "SOL/USD",
    "XRP": "XRP/USD",
    "SUI": "SUI/USD",
}
TIMEFRAMES = ("1h", "4h", "1d")
Fetcher = Callable[[str, str], list[list[float]]]
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"
_KRAKEN_PAIRS = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "SOL/USD": "SOLUSD",
    "XRP/USD": "XRPUSD",
    "SUI/USD": "SUIUSD",
}
_MINUTES = {"1h": 60, "4h": 240, "1d": 1440}


def kraken_public_ohlc(symbol: str, timeframe: str) -> list[list[float]]:
    """
    Public Kraken candles over plain HTTPS GET (no keys, no ccxt).

    Args:
        symbol (str): A value of ``MARKETS``, e.g. ``BTC/USD``.
        timeframe (str): ``1h``, ``4h`` or ``1d``.

    Returns:
        list[list[float]]: ``[[ms, open, high, low, close, volume], ...]`` oldest first.

    Raises:
        ValueError: On an unknown symbol or an error answer from Kraken.
    """
    q = urllib.parse.urlencode({"pair": _KRAKEN_PAIRS[symbol], "interval": _MINUTES[timeframe]})
    req = urllib.request.Request(f"{KRAKEN_OHLC}?{q}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (fixed https URL)
        body = json.loads(resp.read())
    if body.get("error"):
        raise ValueError(f"kraken: {body['error']}")
    rows = next(v for k, v in body["result"].items() if k != "last")
    # Kraken rows: [time_s, open, high, low, close, vwap, volume, count]
    return [
        [int(r[0]) * 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6])]
        for r in rows
    ]


def _num(x: Any) -> float:
    """Decimal or string to float for JSON (display only, never for arithmetic)."""
    return float(Decimal(str(x)))


def _opt(x: Any) -> float | None:
    """``_num`` that passes None through."""
    return None if x is None else _num(x)


def status_snapshot(
    data_root: Path,
    kill_switch: dict[str, Any] | None,
    live_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Summarize every saved forward session for the dashboard.

    Args:
        data_root (Path): Data directory holding ``state/session-*.json``.
        kill_switch (dict[str, Any] | None): Kill-switch state, or None if never set.
        live_gate (dict[str, Any] | None): Owner-approved live requirements to display
            (paper cycles needed, capital cap), or None when unknown.

    Returns:
        dict[str, Any]: ``{kill_switch, sessions, live_gate}``.
    """
    sessions: list[dict[str, Any]] = []
    for f in sorted((data_root / "state").glob("session-*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            meta, led = d["meta"], d["ledger"]
        except (OSError, ValueError, KeyError):
            sessions.append({"name": f.stem, "error": "unreadable state file"})
            continue
        sessions.append(
            {
                "name": f.stem,
                "environment": meta.get("environment"),
                # Reason: cycles this session has run; the live gate counts completed paper
                # cycles itself (`trader live preflight`), so this is a progress display only.
                "cycles": int(d.get("ids", {}).get("cyc", 0)),
                "day_start_usd": _opt(d.get("loss", {}).get("day_start")),
                "high_water_usd": _opt(d.get("loss", {}).get("hwm")),
                "fees_usd": _opt(led.get("fees_usd")),
                "last_bar": meta.get("last_t1"),
                "last_cycle_utc": meta.get("last_cycle_wall_utc"),
                "equity_usd": _num(meta.get("equity_usd", led["cash"])),
                "cash_usd": _num(led["cash"]),
                "positions": [
                    {
                        "instrument": k,
                        "quantity": _num(p["quantity"]),
                        "entry": _num(p["avg_entry_price"]),
                        "stop": None if p.get("stop_price") is None else _num(p["stop_price"]),
                    }
                    for k, p in led["positions"].items()
                ],
                "trades": [
                    {
                        "instrument": t["instrument_id"],
                        "opened_at": str(t["opened_at"]),
                        "closed_at": str(t["closed_at"]),
                        "entry": _num(t["entry_price"]),
                        "exit": _num(t["exit_price"]),
                        "pnl_usd": _num(t["pnl_usd"]),
                    }
                    for t in led["trades"][-50:]
                ],
                "breaker_open": bool(d.get("controls", {}).get("breaker_open")),
                "stale_cycles": meta.get("stale_cycles", 0),
            }
        )
    return {"kill_switch": kill_switch, "sessions": sessions, "live_gate": live_gate}


def fetch_bars(fetch: Fetcher, market: str, timeframe: str) -> list[Bar]:
    """
    Fetch public candles and drop the still-forming last one.

    Args:
        fetch (Fetcher): ``(symbol, timeframe) -> [[ms, o, h, l, c, v], ...]``.
        market (str): A key of ``MARKETS``.
        timeframe (str): ``1h``, ``4h`` or ``1d``.

    Returns:
        list[Bar]: Complete bars, oldest first.

    Raises:
        ValueError: For an unknown market or timeframe.
    """
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        raise ValueError("unknown market or timeframe")
    rows = fetch(MARKETS[market], timeframe)
    bars = [
        Bar(
            datetime.fromtimestamp(r[0] / 1000, tz=UTC),
            Decimal(str(r[1])),
            Decimal(str(r[2])),
            Decimal(str(r[3])),
            Decimal(str(r[4])),
        )
        for r in rows
    ]
    return bars[:-1]


def candles_payload(bars: list[Bar], fast: int = 20, slow: int = 50) -> dict[str, Any]:
    """
    Candles plus the moving averages the strategy reads, in chart-library shape.

    Args:
        bars (list[Bar]): Bars, oldest first.
        fast (int): Fast SMA period.
        slow (int): Slow SMA period.

    Returns:
        dict[str, Any]: ``{candles, sma_fast, sma_slow}`` with UNIX-second times.
    """
    closes: list[Decimal] = []
    candles, f_line, s_line = [], [], []
    for b in bars:
        t = int(b.open_time_utc.timestamp())
        closes.append(b.close)
        candles.append(
            {
                "time": t,
                "open": _num(b.open),
                "high": _num(b.high),
                "low": _num(b.low),
                "close": _num(b.close),
            }
        )
        if (f := sma(closes, fast)) is not None:
            f_line.append({"time": t, "value": _num(f)})
        if (s := sma(closes, slow)) is not None:
            s_line.append({"time": t, "value": _num(s)})
    return {"candles": candles, "sma_fast": f_line, "sma_slow": s_line}


def perps_payload(
    load_params: Callable[[], PerpsParams], market: str, bars: list[Bar]
) -> dict[str, Any]:
    """
    Paper perps replay on one market's bars, or why it cannot run yet.

    Args:
        load_params (Callable[[], PerpsParams]): Loads approved perps parameters.
        market (str): Market name.
        bars (list[Bar]): Bars, oldest first.

    Returns:
        dict[str, Any]: ``{blocked: [...]}`` or a summary with trade markers and equity.
    """
    try:
        params = load_params()
    except PerpsConfigUnresolvedError as exc:
        return {"blocked": exc.keys, "refs": exc.refs}
    if market not in params.markets:
        return {"blocked": [f"market {market} not in perps config"], "refs": []}
    r = run_perps_backtest(params, {market: bars})
    markers = []
    for e in r.events:
        if e["event"] in ("OPENED", "CLOSED", "LIQUIDATED"):
            markers.append(
                {
                    "time": int(datetime.fromisoformat(e["at_utc"]).timestamp()),
                    "event": e["event"],
                    "side": e.get("side"),
                    "price": _num(e.get("entry") or e.get("exit") or e.get("mark") or 0),
                    "liquidation_price": (
                        _num(e["liquidation_price"]) if "liquidation_price" in e else None
                    ),
                }
            )
    return {
        "disclaimer": "Simulated results on historical data. Not a forecast. "
        "Profitability is not guaranteed or implied.",
        "start_equity_usd": _num(r.start_equity_usd),
        "end_equity_usd": _num(r.end_equity_usd),
        "max_drawdown_pct": _num(r.max_drawdown_pct),
        "trades": r.trades,
        "liquidations": r.liquidations,
        "fees_paid_usd": _num(r.fees_paid_usd),
        "rejections": r.rejections,
        "markers": markers,
    }


def watch_payload(
    bars: dict[str, list[Bar]], last: dict[str, float], fast: int = 20, slow: int = 50
) -> list[dict[str, Any]]:
    """
    One row per market for the watchlist: price, 24h change, trend, and a 7-day sparkline.

    ``trend`` is the stance the ``sma_trend`` strategy reads on 4h bars: ``up`` while the
    fast average is above the slow one, else ``down``; None until both averages exist.

    Args:
        bars (dict[str, list[Bar]]): Complete 4h bars per market, oldest first.
        last (dict[str, float]): Latest traded price per market (the forming candle's close).
        fast (int): Fast SMA period.
        slow (int): Slow SMA period.

    Returns:
        list[dict[str, Any]]: Rows in ``MARKETS`` order; a market without bars is skipped.
    """
    rows: list[dict[str, Any]] = []
    for market in MARKETS:
        series = bars.get(market) or []
        if not series:
            continue
        closes = [b.close for b in series]
        price = last.get(market, _num(closes[-1]))
        # Reason: six 4h bars back is the close 24 hours before the latest complete bar.
        day_ago = _num(closes[-7]) if len(closes) >= 7 else None
        f, s = sma(closes, fast), sma(closes, slow)
        rows.append(
            {
                "market": market,
                "price": price,
                "change_24h_pct": None if not day_ago else (price / day_ago - 1) * 100,
                "trend": None if f is None or s is None else ("up" if f > s else "down"),
                "spark": [_num(c) for c in closes[-42:]] + [price],
            }
        )
    return rows
