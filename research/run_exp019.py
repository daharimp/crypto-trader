"""EXP-2026-019: can the 50/200 trend rule also trade downtrends from the short side?

Research only. Spot stays long only (CLAUDE.md safety rules), so every short here is a
paper perps short on Jupiter's markets (BTC, ETH, SOL only). Same replay rules as
EXP-2026-018: decide on the 4h close, fill at the next open, 2 x ATR(14) stop on every
trade (above the entry for shorts), 1% of equity at risk, tier caps, 80% total exposure,
1x (no leverage), 15% breaker with a 7-day pause, 3% daily loss stop, 3-loss cooldown.

Costs: spot 50 bps/side; perps 7 bps/side plus borrow 0.0016%/h (UD-28) and, as a stress
case, 0.01%/h (the earlier cautious value).

Run: uv run python research/run_exp019.py data/raw/candles > research/EXP-2026-019-results.txt
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from run_exp018 import (
    BREAKER,
    BREAKER_PAUSE,
    COINS,
    DAILY_LOSS,
    EXPOSURE_CAP,
    HOLDOUT_DAYS,
    RISK,
    STOP_ATR,
    TIER_CAP,
    Run,
    Trade,
    _cross,
    add_indicators,
    load_bars,
    stats,
)

PERPS_MARKETS = {"BTC", "ETH", "SOL"}


@dataclass(frozen=True)
class Venue:
    """Cost model for one side."""

    name: str
    fee: float  # fraction per side
    borrow_per_hour: float = 0.0


SPOT = Venue("spot", 0.005)
PERPS = Venue("perps", 0.0007, 0.000016)
PERPS_STRESS = Venue("perps-stress", 0.0007, 0.0001)


@dataclass
class Book:
    """Which venue carries each side; None disables that side."""

    long: Venue | None
    short: Venue | None


Signals = Callable[[pd.DataFrame], dict[str, pd.Series]]


def stance(fast: int, slow: int) -> Signals:
    """Long while fast > slow, short while fast < slow."""

    def f(d: pd.DataFrame) -> dict[str, pd.Series]:
        up = d[f"sma{fast}"] > d[f"sma{slow}"]
        return {"enter_L": up, "exit_L": ~up, "enter_S": ~up, "exit_S": up}

    return f


def cross_both() -> Signals:
    """Long on the 20/50 cross up, short on the cross down; exit on the opposite stance."""

    def f(d: pd.DataFrame) -> dict[str, pd.Series]:
        fa, sl = d["sma20"], d["sma50"]
        up = fa > sl
        down_x = (fa < sl) & (fa.shift() >= sl.shift())
        return {"enter_L": _cross(d), "exit_L": ~up, "enter_S": down_x, "exit_S": up}

    return f


@dataclass
class Pos:
    coin: str
    side: int  # +1 long, -1 short
    qty: float
    entry: float
    stop: float
    opened: pd.Timestamp
    venue: Venue


def value(p: Pos, px: float) -> float:
    """Collateral-style value: long = qty*px, short = qty*(2*entry - px)."""
    return p.qty * px if p.side > 0 else p.qty * (2 * p.entry - px)


def replay(
    data: dict[str, pd.DataFrame], sig: Signals, book: Book, start: pd.Timestamp, end: pd.Timestamp
) -> Run:
    """Replay a long/short rule set on the portfolio."""
    sigs = {c: sig(df) for c, df in data.items()}
    idx = [t for t in sorted(set().union(*[df.index for df in data.values()])) if start <= t < end]
    if not idx:
        return Run(pd.Series([2500.0], index=[start]))
    cash = peak = 2500.0
    pos: dict[str, Pos] = {}
    pending: dict[str, tuple] = {}
    losses = dict.fromkeys(data, 0)
    cool: dict[str, pd.Timestamp] = {}
    day, day_eq = None, cash
    trades: list[Trade] = []
    curve: dict[pd.Timestamp, float] = {}
    paused: pd.Timestamp | None = None
    trips: list[pd.Timestamp] = []

    def close(p: Pos, px: float, t: pd.Timestamp, why: str) -> None:
        nonlocal cash
        hours = (t - p.opened).total_seconds() / 3600
        borrow = p.qty * p.entry * p.venue.borrow_per_hour * hours
        out = value(p, px) - p.qty * px * p.venue.fee - borrow
        cost_in = p.qty * p.entry * (1 + p.venue.fee)
        cash += out
        pnl = out - cost_in
        trades.append(
            Trade(p.coin, "L" if p.side > 0 else "S", p.opened, t, pnl, pnl / cost_in, why)
        )
        if pnl < 0:
            losses[p.coin] += 1
            if losses[p.coin] >= 3:
                cool[p.coin], losses[p.coin] = t + pd.Timedelta(hours=24), 0
        else:
            losses[p.coin] = 0
        del pos[p.coin]

    for t in idx:
        for coin, act in list(pending.items()):
            df = data[coin]
            if t not in df.index:
                continue
            o = df.at[t, "open"]
            if act[0] == "exit" and coin in pos:
                close(pos[coin], o, t, "signal")
            elif act[0] == "enter" and coin not in pos:
                _, side, stop_frac, qty, venue = act
                qty = min(qty, cash / (o * (1 + venue.fee)))
                if qty > 0:
                    cash -= qty * o * (1 + venue.fee)
                    stop = o * (1 - side * stop_frac)
                    pos[coin] = Pos(coin, side, qty, o, stop, t, venue)
            del pending[coin]
        for coin in list(pos):
            df = data[coin]
            if t not in df.index:
                continue
            p, row = pos[coin], df.loc[t]
            if p.side > 0 and row["low"] <= p.stop:
                close(p, min(row["open"], p.stop), t, "stop")
            elif p.side < 0 and row["high"] >= p.stop:
                close(p, max(row["open"], p.stop), t, "stop")
        mtm = cash + sum(
            value(p, data[c].at[t, "close"] if t in data[c].index else p.entry)
            for c, p in pos.items()
        )
        curve[t] = mtm
        peak = max(peak, mtm)
        if day != t.date():
            day, day_eq = t.date(), mtm
        if paused is not None and t >= paused:
            paused, peak = None, mtm
        dd = 1 - mtm / peak
        if dd >= BREAKER and paused is None:
            trips.append(t)
            paused = t + BREAKER_PAUSE
        for coin, df in data.items():
            if t not in df.index:
                continue
            s = sigs[coin]
            if coin in pos:
                key = "exit_L" if pos[coin].side > 0 else "exit_S"
                if bool(s[key].get(t, False)):
                    pending[coin] = ("exit",)
                continue
            if paused is not None or mtm < day_eq * (1 - DAILY_LOSS):
                continue
            if coin in cool and t < cool[coin]:
                continue
            side, venue = 0, None
            if book.long and bool(s["enter_L"].get(t, False)):
                side, venue = 1, book.long
            elif book.short and coin in PERPS_MARKETS and bool(s["enter_S"].get(t, False)):
                side, venue = -1, book.short
            if not side:
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
            gross = sum(
                p.qty * data[c].at[t, "close"] for c, p in pos.items() if t in data[c].index
            )
            cap = min(TIER_CAP[coin] * mtm, EXPOSURE_CAP * mtm - gross)
            qty = min(qty, max(cap, 0) / row["close"])
            if qty * row["close"] >= 10:
                pending[coin] = ("enter", side, stop_frac, qty, venue)
    last = idx[-1]
    for coin in list(pos):
        if last in data[coin].index:
            close(pos[coin], data[coin].at[last, "close"], last, "end")
    return Run(pd.Series(curve), trades, trips)


RULES: list[tuple[str, Signals, Book]] = [
    ("50/200 long only (spot)              ", stance(50, 200), Book(SPOT, None)),
    ("50/200 short only (perps)            ", stance(50, 200), Book(None, PERPS)),
    ("50/200 long spot + short perps       ", stance(50, 200), Book(SPOT, PERPS)),
    ("50/200 long spot + short perps STRESS", stance(50, 200), Book(SPOT, PERPS_STRESS)),
    ("50/200 long+short all on perps       ", stance(50, 200), Book(PERPS, PERPS)),
    ("20/50 cross both ways, spot + perps  ", cross_both(), Book(SPOT, PERPS)),
    ("20/50 stance both ways, spot + perps ", stance(20, 50), Book(SPOT, PERPS)),
]


def main(folder: str) -> None:
    """Run every rule set on each window and split results by side."""
    data = {}
    for c in COINS:
        p = Path(folder) / f"{c.lower()}_usd_1h.csv"
        if p.exists():
            data[c] = add_indicators(load_bars(p, "4h"))
    end = min(df.index[-1] for df in data.values()) + pd.Timedelta(hours=4)
    first = max(df.index[0] for df in data.values()) + pd.Timedelta(days=40)
    hold = end - pd.Timedelta(days=HOLDOUT_DAYS)
    windows = {
        f"development {first.date()}..{hold.date()}": (first, hold),
        f"holdout (last {HOLDOUT_DAYS}d) {hold.date()}..{end.date()}": (hold, end),
        "recent downtrend (last 60d)": (end - pd.Timedelta(days=60), end),
        "live paper period from 2026-11-15": (pd.Timestamp("2026-11-15", tz="UTC"), end),
    }
    print("EXP-2026-019 long/short trend rules. Shorts only on perps BTC/ETH/SOL, 1x.")
    print("Every trade: 2xATR stop, 1% risk. Long PnL / short PnL split in the last columns.")
    for w, (a, b) in windows.items():
        print(f"\n== {w}")
        print(
            f"{'rule':<40}{'trades':>7}{'/mo':>6}{'win':>6}{'return':>8}{'maxDD':>7}"
            f"{'sharpe':>7}{'PF':>6}{'trips':>6}{'L n':>5}{'L $':>8}{'S n':>5}{'S $':>8}"
        )
        for name, sig, book in RULES:
            run = replay(data, sig, book, a, b)
            s = stats(run)
            ln = [t for t in run.trades if t.mode == "L"]
            sh = [t for t in run.trades if t.mode == "S"]
            print(
                f"{name:<40}{s['trades']:>7}{s['per_month']:>6.1f}{s['win'] * 100:>5.0f}%"
                f"{s['ret'] * 100:>7.1f}%{s['dd'] * 100:>6.1f}%{s['sharpe']:>7.2f}{s['pf']:>6.2f}"
                f"{len(run.breaker_trips):>6}{len(ln):>5}{sum(t.pnl for t in ln):>8.0f}"
                f"{len(sh):>5}{sum(t.pnl for t in sh):>8.0f}"
            )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/candles")
