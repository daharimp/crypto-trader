"""Degen replay: 1h/4h/1d trend alignment at 2 daily moves of buffer, week by week.

EXPLORATORY, not pre-registered (owner request, 2026-11-15): it answers "what would the
proposed degen paper account have done, week by week, recently and over the past years?"
before that account is built. Research only; changes no configuration.

Degen rule, decided each hour from completed candles only:
- 1h trend: sign of the last 24 hours' return (1h closes);
- 4h trend: sign of the last 7 days' return (last completed 4h closes, 42 bars);
- 1d trend: sign of the last 30 days' return (last completed daily closes, 30 bars);
- long when all three are up, short when all three are down, flat otherwise.
Leverage: ADR-032's rule with 2 typical daily moves of buffer, the daily move measured on
30 days of 4h closes (a 1h feed of 720 candles cannot hold 30 days plus one), between 1x and
25x, and no open whose liquidation would be closer than 3.5% (the paper risk floor, UD-27).

Baseline: the running paper account (4h candles, 30-day trend, 4 daily moves, same floor).
Both: $250 collateral per trade per coin (10% of $2,500), fees 7 bps per side, 20 bps
maintenance, measured Deribit funding, liquidation on each bar's adverse extreme.

Usage: uv run python research/degen_replay.py
Needs data/hourly/<coin>_usd_1h.csv, data/long/<coin>_usd_4h.csv, data/funding/deribit_<coin>.csv.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd

from trader.perps.leverage_replay import Replay, Venue, assessed_leverage, replay
from trader.research.funding import load_funding, per_bar
from trader.research.lab import load_csv

COINS = ("btc", "eth", "sol")
VENUE = Venue()
FLOOR = 0.035  # minimum liquidation distance (UD-27)
RECENT_WEEKS = 26
H = pd.Timedelta(hours=1)


def completed(close_1h: pd.Series, rule: str, hours: int) -> pd.Series:
    """Closes of complete ``rule`` bars, indexed by the 1h bar whose close completes them."""
    grouped = close_1h.resample(rule, label="left", closed="left")
    out = grouped.last()[grouped.count() == hours]
    # Reason: a bin opening at T is known at T + hours, i.e. at the close of the 1h bar
    # opening at T + hours - 1; earlier 1h bars must not see it.
    out.index = out.index + (hours - 1) * H
    return out


def on_hours(s: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Carry a higher-timeframe series forward onto the 1h index (past values only)."""
    return s.reindex(s.index.union(index)).ffill().reindex(index)


def floored(lev: pd.Series) -> pd.Series:
    """Leverage, NaN where the liquidation distance would fall below the risk floor."""
    distance = 1 / lev - (2 * VENUE.fee_bps + VENUE.maintenance_bps) / 10_000
    return lev.where(distance >= FLOOR)


def degen(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Desired side after each 1h close and the opening leverage assessed there."""
    c = df["close"]
    c4, cd = completed(c, "4h", 4), completed(c, "1D", 24)
    t1 = np.sign(c.pct_change(24))
    t4 = on_hours(np.sign(c4.pct_change(42)), df.index)
    td = on_hours(np.sign(cd.pct_change(30)), df.index)
    side = t1.where((t1 == t4) & (t1 == td), 0.0).fillna(0.0)
    move = on_hours(c4.pct_change().rolling(180).std() * math.sqrt(6), df.index)
    return side, floored(assessed_leverage(move, 2.0, VENUE))


def baseline(df4: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """The running paper account: 30-day trend on 4h candles at 4 daily moves."""
    c = df4["close"]
    side = np.sign(c.pct_change(180)).fillna(0.0)
    move = c.pct_change().rolling(180).std() * math.sqrt(6)
    return side, floored(assessed_leverage(move, 4.0, VENUE))


def weekly(r: Replay, index: pd.DatetimeIndex) -> pd.Series:
    """Dollars per calendar week (Monday start, UTC)."""
    return pd.Series(r.pnl, index=index).resample("W-SUN", label="left", closed="left").sum()


def run(name: str, df: pd.DataFrame, side: pd.Series, lev: pd.Series, fund: pd.Series, a: int):
    """Replay from bar ``a`` to the last bar with a known next open."""
    b = len(df) - 1
    r = replay(df, side, lev, fund, VENUE, a, b)
    held = float((side.shift(1).iloc[a:b] != 0).mean() * 100)
    avg = float(np.mean([t["lev"] for t in r.trades])) if r.trades else 0.0
    return r, weekly(r, df.index[a:b]), held, avg


def summary(label: str, weeks: pd.Series, liqs: int, trades: int, held: float, avg: float) -> str:
    """One row of weekly statistics."""
    w = weeks
    return (
        f"{label:<26}{len(w):>6}{w.sum():>11,.0f}{w.mean():>9,.0f}{w.median():>9,.0f}"
        f"{(w > 0).mean() * 100:>8.0f}%{w.max():>9,.0f}{w.min():>9,.0f}{trades:>8}{liqs:>6}"
        f"{held:>9.0f}%{avg:>7.1f}"
    )


HEAD = (
    f"{'':<26}{'weeks':>6}{'total $':>11}{'avg wk':>9}{'median':>9}{'win wks':>9}"
    f"{'best wk':>9}{'worst wk':>9}{'trades':>8}{'liqs':>6}{'in mkt':>10}{'lev':>7}"
)


def main() -> None:
    """Print provenance, per-coin and whole-account weekly results, recent and full history."""
    print("=== Data files (rows, first, last, sha256) ===")
    for c in COINS:
        for path in (
            f"data/hourly/{c}_usd_1h.csv",
            f"data/long/{c}_usd_4h.csv",
            f"data/funding/deribit_{c}.csv",
        ):
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            print(
                f"  {path}: {len(lines) - 1} rows, {lines[1].split(',')[0]} to {lines[-1].split(',')[0]}, {digest[:16]}"
            )

    acct: dict[str, list[pd.Series]] = {"DEGEN": [], "BASELINE": []}
    stats: dict[str, list[tuple[int, int]]] = {"DEGEN": [], "BASELINE": []}
    for c in COINS:
        df = load_csv(f"data/hourly/{c}_usd_1h.csv")
        df4 = load_csv(f"data/long/{c}_usd_4h.csv")
        hourly = load_funding(f"data/funding/deribit_{c}.csv")
        f1 = hourly.reindex(df.index)
        f4 = per_bar(hourly, df4.index)
        # Reason: start both where degen has its 30 daily closes and 30 days of 4h volatility
        # and funding exists, so every week compared is the same week.
        start = max(df.index[0] + pd.Timedelta(days=62), hourly.index[0])
        start = start.ceil("D") + pd.Timedelta(days=(7 - start.ceil("D").dayofweek) % 7)
        a1, a4 = int(df.index.searchsorted(start)), int(df4.index.searchsorted(start))
        print(f"\n=== {c.upper()} from {start.date()} (1h bars {len(df) - 1 - a1}) ===")
        print(HEAD)
        rows = {
            "DEGEN": run("DEGEN", df, *degen(df), f1, a1),
            "BASELINE": run("BASELINE", df4, *baseline(df4), f4, a4),
        }
        for name, (r, w, held, avg) in rows.items():
            acct[name].append(w)
            stats[name].append((r.liquidations, len(r.trades)))
            print(summary(f"{name} all", w, r.liquidations, len(r.trades), held, avg))
            print(
                summary(f"{name} last {RECENT_WEEKS} wks", w.iloc[-RECENT_WEEKS:], 0, 0, 0, 0)[:-31]
            )

    print("\n=== Whole account: BTC + ETH + SOL together, $250 collateral each per trade ===")
    print("(weeks before every coin has data are left out)")
    print(HEAD[:-31])
    totals = {}
    for name, parts in acct.items():
        w = pd.concat(parts, axis=1).dropna().sum(axis=1)
        totals[name] = w
        print(summary(f"{name} all", w, 0, 0, 0, 0)[:-31])
        print(summary(f"{name} last {RECENT_WEEKS} wks", w.iloc[-RECENT_WEEKS:], 0, 0, 0, 0)[:-31])
    by_year = pd.DataFrame(totals).groupby(lambda t: t.year).sum()
    print("\nwhole account, dollars per calendar year (context):")
    print(by_year.round(0).to_string())
    last = pd.DataFrame(totals).iloc[-8:].round(0)
    last.index = [d.date() for d in last.index]
    print("\nwhole account, last 8 weeks (week starting Monday):")
    print(last.to_string())
    print("\nExploratory replay on past prices; not pre-registered and not a forecast.")


if __name__ == "__main__":
    main()
