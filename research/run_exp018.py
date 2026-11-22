"""EXP-2026-018: why spot never trades, and which entry rules would (research only).

Portfolio replay that mirrors the paper spot engine closely enough to compare entry rules:

* 4h bars built from 1h Coinbase candles (complete buckets only).
* Decide on the close of bar i, fill at the open of bar i+1 (no look-ahead).
* Every entry gets the approved hard stop: 2 x Wilder ATR(14) below the fill (UD-16).
  The stop is checked inside every bar from the fill bar on; a gap through it fills at the
  open. Signal exits fill at the next open.
* Sizing: 1% of equity at risk per trade (UD-03), capped per asset tier (35/15/5%),
  80% total exposure (UD-12), cash only, long only, no leverage.
* Drawdown step-down (UD-15) and the 15% breaker (UD-01), 3% daily loss stop (UD-02),
  3-loss / 24h cooldown per coin (UD-17).
* Costs: 50 bps per side (0.40% fee + 0.10% slippage, the shipped base scenario).

Run: uv run python research/run_exp018.py data/raw/candles > research/EXP-2026-018-results.txt
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

COINS = ("BTC", "ETH", "SOL", "XRP", "SUI")
TIER_CAP = {"BTC": 0.35, "ETH": 0.35, "SOL": 0.15, "XRP": 0.15, "SUI": 0.05}
COST = 0.005
RISK = 0.01
STOP_ATR = 2.0
EXPOSURE_CAP = 0.80
BREAKER = 0.15
DAILY_LOSS = 0.03
HOLDOUT_DAYS = 180


# ---------------------------------------------------------------- data and indicators


def load_bars(path: Path, tf: str = "4h") -> pd.DataFrame:
    """Load a 1h CSV and build complete ``tf`` bars aligned to 00:00 UTC."""
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df.pop("open_time_utc"), utc=True)
    df = df.astype(float).sort_index()
    df = df[~df.index.duplicated()]
    if tf == "1h":
        return df[["open", "high", "low", "close", "volume"]]
    g = df.resample(tf, origin="epoch")
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
            "n": g["close"].count(),
        }
    )
    return out[out["n"] == 4].drop(columns="n")


def wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing (alpha = 1/n)."""
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add the features-m2 equivalents used by the live strategies."""
    c = df["close"]
    d = df.copy()
    for n in (20, 50, 200):
        d[f"sma{n}"] = c.rolling(n).mean()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - c.shift()).abs(), (df["low"] - c.shift()).abs()],
        axis=1,
    ).max(axis=1)
    d["atr"] = wilder(tr, 14)
    delta = c.diff()
    up, dn = wilder(delta.clip(lower=0), 14), wilder((-delta).clip(lower=0), 14)
    d["rsi"] = 100 - 100 / (1 + up / dn)
    std = c.rolling(20).std(ddof=0)
    d["bb_lo"], d["bb_mid"] = d["sma20"] - 2 * std, d["sma20"]
    return d


# ---------------------------------------------------------------- entry / exit rules
# Each rule returns (entry, exit_trend, exit_mr, mode) arrays evaluated at bar close.
# mode[i] says which exit applies to a position opened from bar i ("T" trend, "M" reversion).

Rule = Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]


def _cross(d: pd.DataFrame) -> pd.Series:
    f, s = d["sma20"], d["sma50"]
    return (f > s) & (f.shift() <= s.shift())


def _mr_entry(d: pd.DataFrame, rsi_max: float, need_band: bool = True) -> pd.Series:
    e = d["rsi"] < rsi_max
    return e & (d["close"] < d["bb_lo"]) if need_band else e


def _mr_exit(d: pd.DataFrame) -> pd.Series:
    return (d["close"] >= d["bb_mid"]) | (d["rsi"] > 50)


@dataclass
class Spec:
    """One rule set: entry signal, mode per entry, and exits per mode."""

    name: str
    build: Callable[[pd.DataFrame], dict[str, pd.Series]]


def spec_current(d: pd.DataFrame) -> dict[str, pd.Series]:
    """sma_trend 1.0.0 as running today: buy only on the cross-up bar."""
    return {"entry_T": _cross(d), "exit_T": d["sma20"] < d["sma50"]}


def spec_stance(fast: int, slow: int) -> Callable[[pd.DataFrame], dict[str, pd.Series]]:
    """Hold while fast > slow (enter on any bar in an uptrend, not just the cross bar)."""

    def f(d: pd.DataFrame) -> dict[str, pd.Series]:
        up = d[f"sma{fast}"] > d[f"sma{slow}"]
        return {"entry_T": up, "exit_T": ~up}

    return f


def spec_mr(rsi_max: float, trend: bool = False) -> Callable[[pd.DataFrame], dict[str, pd.Series]]:
    """mean_reversion: RSI < x and close under the lower band; exit at mid band or RSI > 50."""

    def f(d: pd.DataFrame) -> dict[str, pd.Series]:
        e = _mr_entry(d, rsi_max)
        if trend:
            e &= d["close"] > d["sma200"]
        return {"entry_M": e, "exit_M": _mr_exit(d)}

    return f


def spec_hybrid(rsi_max: float, stance: bool) -> Callable[[pd.DataFrame], dict[str, pd.Series]]:
    """Trend entries in an uptrend, oversold reversion entries in a downtrend."""

    def f(d: pd.DataFrame) -> dict[str, pd.Series]:
        up = d["sma20"] > d["sma50"]
        trend_e = up if stance else _cross(d)
        return {
            "entry_T": trend_e,
            "exit_T": ~up,
            "entry_M": (~up) & _mr_entry(d, rsi_max),
            "exit_M": _mr_exit(d),
        }

    return f


SPECS = [
    Spec("A current: SMA20/50 cross bar only", spec_current),
    Spec("B SMA20/50 stance (any uptrend bar)", spec_stance(20, 50)),
    Spec("C SMA50/200 stance", spec_stance(50, 200)),
    Spec("D mean_reversion RSI<30 + lower band", spec_mr(30)),
    Spec("E mean_reversion RSI<35 + lower band", spec_mr(35)),
    Spec("F mean_reversion RSI<30, only above SMA200", spec_mr(30, trend=True)),
    Spec("G hybrid: cross + reversion<30 in downtrend", spec_hybrid(30, stance=False)),
    Spec("H hybrid: stance + reversion<30 in downtrend", spec_hybrid(30, stance=True)),
    Spec("I hybrid: stance + reversion<35 in downtrend", spec_hybrid(35, stance=True)),
]
SPECS_1H = [
    Spec("A current rule", spec_current),
    Spec("C SMA50/200 stance", spec_stance(50, 200)),
]


# ---------------------------------------------------------------- portfolio replay


@dataclass
class Pos:
    coin: str
    mode: str
    qty: float
    entry: float
    stop: float
    opened: pd.Timestamp


@dataclass
class Trade:
    coin: str
    mode: str
    opened: pd.Timestamp
    closed: pd.Timestamp
    pnl: float
    ret: float
    reason: str


@dataclass
class Run:
    equity: pd.Series
    trades: list[Trade] = field(default_factory=list)
    breaker_trips: list[pd.Timestamp] = field(default_factory=list)


# Reason: the live breaker needs an owner reset (UD-01). A permanent halt would freeze every
# rule set after its first trip and hide the rest of the window, so the replay models an
# owner review: no new entries for 7 days, then the peak resets to current equity.
BREAKER_PAUSE = pd.Timedelta(days=7)


def replay(
    data: dict[str, pd.DataFrame], spec: Spec, start: pd.Timestamp, end: pd.Timestamp
) -> Run:
    """Replay one rule set on the portfolio between ``start`` and ``end``."""
    sig = {c: spec.build(df) for c, df in data.items()}
    idx = sorted(set().union(*[df.index for df in data.values()]))
    idx = [t for t in idx if start <= t < end]
    if not idx:
        return Run(pd.Series([2500.0], index=[start]))
    cash, peak = 2500.0, 2500.0
    pos: dict[str, Pos] = {}
    pending: dict[str, tuple[str, float]] = {}  # coin -> ("enter", mode) / ("exit", 0)
    losses: dict[str, int] = dict.fromkeys(data, 0)
    cool_until: dict[str, pd.Timestamp] = {}
    day, day_start_eq = None, cash
    trades: list[Trade] = []
    eq_curve = {}
    paused_until: pd.Timestamp | None = None
    trips: list[pd.Timestamp] = []

    def close(p: Pos, px: float, t: pd.Timestamp, why: str) -> None:
        nonlocal cash
        proceeds = p.qty * px * (1 - COST)
        cost = p.qty * p.entry * (1 + COST)
        cash += proceeds
        pnl = proceeds - cost
        trades.append(Trade(p.coin, p.mode, p.opened, t, pnl, pnl / cost, why))
        if pnl < 0:
            losses[p.coin] += 1
            if losses[p.coin] >= 3:
                cool_until[p.coin] = t + pd.Timedelta(hours=24)
                losses[p.coin] = 0
        else:
            losses[p.coin] = 0
        del pos[p.coin]

    for t in idx:
        # 1) fills at this bar's open for decisions made on the previous close
        for coin, (act, mode_or_stop) in list(pending.items()):
            df = data[coin]
            if t not in df.index:
                continue
            o = df.at[t, "open"]
            if act == "exit" and coin in pos:
                close(pos[coin], o, t, "signal")
            elif act == "enter" and coin not in pos:
                mode, stop_frac, qty = mode_or_stop
                qty = min(qty, cash / (o * (1 + COST)))
                if qty > 0:
                    cash -= qty * o * (1 + COST)
                    pos[coin] = Pos(coin, mode, qty, o, o * (1 - stop_frac), t)
            del pending[coin]
        # 2) protective stops inside the bar
        for coin in list(pos):
            df = data[coin]
            if t not in df.index:
                continue
            p = pos[coin]
            if df.at[t, "low"] <= p.stop:
                close(p, min(df.at[t, "open"], p.stop), t, "stop")
        # 3) mark to market at the close
        mtm = cash + sum(
            p.qty * data[c].at[t, "close"] if t in data[c].index else p.qty * p.entry
            for c, p in pos.items()
        )
        eq_curve[t] = mtm
        peak = max(peak, mtm)
        if day != t.date():
            day, day_start_eq = t.date(), mtm
        if paused_until is not None and t >= paused_until:
            paused_until, peak = None, mtm
        dd = 1 - mtm / peak
        if dd >= BREAKER and paused_until is None:
            trips.append(t)
            paused_until = t + BREAKER_PAUSE
        # 4) decisions on this close
        for coin, df in data.items():
            if t not in df.index:
                continue
            s = sig[coin]
            if coin in pos:
                p = pos[coin]
                ex = s.get(f"exit_{p.mode}")
                if ex is not None and bool(ex.get(t, False)):
                    pending[coin] = ("exit", 0)
                continue
            if paused_until is not None or mtm < day_start_eq * (1 - DAILY_LOSS):
                continue
            if coin in cool_until and t < cool_until[coin]:
                continue
            mode = None
            for m in ("T", "M"):
                e = s.get(f"entry_{m}")
                if e is not None and bool(e.get(t, False)):
                    mode = m
                    break
            if mode is None:
                continue
            row = df.loc[t]
            if np.isnan(row["atr"]) or np.isnan(row["sma200"]):
                continue
            stop_frac = STOP_ATR * row["atr"] / row["close"]
            if not 0 < stop_frac < 1:
                continue
            frac = dd / BREAKER
            mult = 1.0 if frac < 1 / 3 else 0.5 if frac < 2 / 3 else 0.25
            qty = RISK * mult * mtm / (stop_frac * row["close"])
            exposure = sum(
                p.qty * df_c.at[t, "close"] for c, p in pos.items() if t in (df_c := data[c]).index
            )
            cap = min(TIER_CAP[coin] * mtm, EXPOSURE_CAP * mtm - exposure)
            qty = min(qty, max(cap, 0) / row["close"])
            if qty * row["close"] < 10:
                continue
            pending[coin] = ("enter", (mode, stop_frac, qty))
    # close anything open at the last close for accounting
    last = idx[-1]
    for coin in list(pos):
        if last in data[coin].index:
            close(pos[coin], data[coin].at[last, "close"], last, "end")
    return Run(pd.Series(eq_curve), trades, trips)


def stats(run: Run) -> dict[str, float]:
    """Summary statistics for one replay."""
    eq = run.equity
    if len(eq) < 2:
        return dict.fromkeys(
            ("trades", "per_month", "win", "ret", "dd", "sharpe", "pf", "stops"), 0.0
        )
    daily = eq.resample("1D").last().dropna()
    r = daily.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0
    dd = float((1 - eq / eq.cummax()).max())
    wins = [t for t in run.trades if t.pnl > 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in run.trades if t.pnl <= 0)
    months = max((eq.index[-1] - eq.index[0]).days / 30.4, 1e-9)
    return {
        "trades": len(run.trades),
        "per_month": len(run.trades) / months,
        "win": len(wins) / len(run.trades) if run.trades else 0.0,
        "ret": float(eq.iloc[-1] / eq.iloc[0] - 1),
        "dd": dd,
        "sharpe": sharpe,
        "pf": gross_win / gross_loss if gross_loss > 0 else float("inf"),
        "stops": sum(t.reason == "stop" for t in run.trades),
    }


def main(folder: str) -> None:
    """Run every rule set on development, holdout and the recent downtrend window."""
    data, data_1h = {}, {}
    for c in COINS:
        p = Path(folder) / f"{c.lower()}_usd_1h.csv"
        if p.exists():
            data[c] = add_indicators(load_bars(p, "4h"))
            data_1h[c] = add_indicators(load_bars(p, "1h"))
    end = min(df.index[-1] for df in data.values()) + pd.Timedelta(hours=4)
    first = max(df.index[0] for df in data.values() if len(df) > 1500) + pd.Timedelta(days=40)
    hold = end - pd.Timedelta(days=HOLDOUT_DAYS)
    recent = end - pd.Timedelta(days=60)
    live = pd.Timestamp("2026-11-15", tz="UTC")
    windows = {
        f"development {first.date()}..{hold.date()}": (first, hold),
        f"holdout (last {HOLDOUT_DAYS}d) {hold.date()}..{end.date()}": (hold, end),
        f"recent downtrend (last 60d) {recent.date()}..{end.date()}": (recent, end),
        f"live paper period {live.date()}..{end.date()}": (live, end),
    }
    print("EXP-2026-018 spot entry rules. $2,500 paper, 1% risk, 2xATR stop on every entry,")
    print("50 bps/side, tier caps 35/15/5%, 80% exposure cap, breaker 15%, long only.")
    print(
        "Coins:",
        ", ".join(f"{c} ({len(df)} bars from {df.index[0].date()})" for c, df in data.items()),
    )
    for c, df in data.items():
        bh = {w: df["close"].asof(b) / df["close"].asof(a) - 1 for w, (a, b) in windows.items()}
        print(f"  B&H {c}: " + " | ".join(f"{v * 100:+.0f}%" for v in bh.values()))
    for w, (a, b) in windows.items():
        print(f"\n== {w}")
        print(
            f"{'rule':<46}{'trades':>7}{'/mo':>6}{'win':>6}{'return':>8}{'maxDD':>7}{'sharpe':>7}{'PF':>6}{'stops':>6} trips"
        )
        runs = [(spec.name, replay(data, spec, a, b)) for spec in SPECS]
        runs += [
            (f"{n} [1h bars]", replay(data_1h, sp, a, b)) for sp in SPECS_1H for n in [sp.name]
        ]
        for name, run in runs:
            s = stats(run)
            print(
                f"{name:<46}{s['trades']:>7}{s['per_month']:>6.1f}{s['win'] * 100:>5.0f}%"
                f"{s['ret'] * 100:>7.1f}%{s['dd'] * 100:>6.1f}%{s['sharpe']:>7.2f}{s['pf']:>6.2f}"
                f"{s['stops']:>6} {len(run.breaker_trips):>5}"
            )
    print(
        "\nLive paper period: every 4h SMA20/50 cross-up bar per coin (what sma_trend would buy):"
    )
    for c, df in data.items():
        cr = _cross(df)
        hits = [t for t in df.index[cr.fillna(False).to_numpy()] if t >= live]
        last = df.index[cr.fillna(False).to_numpy()][-1] if cr.any() else None
        row = df.iloc[-1]
        print(
            f"  {c}: crosses since {live.date()}: {[str(h) for h in hits] or 'none'}; last cross {last};"
            f" now sma20/sma50 = {row['sma20'] / row['sma50'] - 1:+.2%}"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/candles")
