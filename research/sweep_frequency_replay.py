"""Sweep frequency replay: the running rule deciding every hour vs every 4 hours.

EXPLORATORY (owner request, 2026-11-16: "it should sweep more often for trades"). Every input
below was fixed in this file and committed before any result was computed. Research only;
changes no configuration. Buffers are the approved 4 (main, UD-26) and the degen account's
3 (UD-29, PR #41); nothing else is new.

Same rule in both: long while the price is above its level 30 days ago, short while below
(``tsmom_30d``). 4H decides at each 4h close from 180 4h closes (the running account). 1H
decides at each 1h close from 720 1h closes. Leverage in both: ADR-032 at the buffer, from
the typical daily move measured on 30 days of COMPLETED 4h closes (the live 1h feed cannot
hold 30 days plus one hour), 1x to 25x, liquidation at least 3.5% away (UD-27). $250
collateral per trade per coin, 7 bps fee per side, 20 bps maintenance, measured Deribit
funding (each hour's own rate at 1h, the 4h sum at 4h), liquidation on each bar's adverse
extreme, positions valued at each close. SOL + BTC + ETH summed as one account.

Usage: uv run python research/sweep_frequency_replay.py
Needs data/hourly/<coin>_usd_1h.csv, data/long/<coin>_usd_4h.csv, data/funding/deribit_<coin>.csv.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from degen_replay import VENUE, floored

from trader.perps.leverage_replay import assessed_leverage, replay
from trader.research.funding import load_funding, per_bar
from trader.research.lab import load_csv

COINS = ("sol", "btc", "eth")
START = pd.Timestamp("2022-01-10", tz="UTC")
RECENT_WEEKS = 26


def move_4h(df4: pd.DataFrame) -> pd.Series:
    """Typical daily move from 30 days of 4h closes, indexed by 4h open time."""
    return df4["close"].pct_change().rolling(180).std() * math.sqrt(6)


def run_4h(coin: str, buf: float) -> tuple[pd.Series, int, int, float]:
    """Dollars per 4h bar from START, trades, liquidations, fees paid."""
    df4 = load_csv(f"data/long/{coin}_usd_4h.csv")
    fund = per_bar(load_funding(f"data/funding/deribit_{coin}.csv"), df4.index)
    side = np.sign(df4["close"].pct_change(180)).fillna(0.0)
    lev = floored(assessed_leverage(move_4h(df4), buf, VENUE))
    a, b = int(df4.index.searchsorted(START)), len(df4) - 1
    r = replay(df4, side, lev, fund, VENUE, a, b)
    fees = sum(2 * t["size"] * VENUE.fee_bps / 10_000 for t in r.trades)
    return pd.Series(r.pnl, index=df4.index[a:b]), len(r.trades), r.liquidations, fees


def run_1h(coin: str, buf: float) -> tuple[pd.Series, int, int, float]:
    """Dollars per 1h bar from START, trades, liquidations, fees paid."""
    df1 = load_csv(f"data/hourly/{coin}_usd_1h.csv")
    df4 = load_csv(f"data/long/{coin}_usd_4h.csv")
    hourly = load_funding(f"data/funding/deribit_{coin}.csv")
    fund = hourly.reindex(df1.index)
    side = np.sign(df1["close"].pct_change(720)).fillna(0.0)
    # Reason: a 4h candle is complete at the close of its last hour (open + 3h), so its
    # volatility is usable from that 1h bar on; earlier hours keep the previous value.
    mv = move_4h(df4)
    mv.index = mv.index + pd.Timedelta(hours=3)
    mv1 = mv.reindex(mv.index.union(df1.index)).ffill().reindex(df1.index)
    lev = floored(assessed_leverage(mv1, buf, VENUE))
    a, b = int(df1.index.searchsorted(START)), len(df1) - 1
    r = replay(df1, side, lev, fund, VENUE, a, b)
    fees = sum(2 * t["size"] * VENUE.fee_bps / 10_000 for t in r.trades)
    return pd.Series(r.pnl, index=df1.index[a:b]), len(r.trades), r.liquidations, fees


def main() -> None:
    """Print the whole-account comparison and the last 8 weeks."""
    print(f"Whole account (SOL + BTC + ETH, $250 per trade per coin) from {START.date()}\n")
    print(
        f"{'':<14}{'total $':>10}{'last 26 wk':>12}{'trades':>8}{'flips/wk':>9}{'fees $':>9}"
        f"{'liqs':>6}{'12h up':>8}{'worst 12h':>10}{'max drop':>10}"
    )
    weekly = {}
    for buf in (4.0, 3.0):
        for name, fn in (("4H", run_4h), ("1H", run_1h)):
            parts, trades, liqs, fees = [], 0, 0, 0.0
            for c in COINS:
                s, t, lq, f = fn(c, buf)
                parts.append(s)
                trades, liqs, fees = trades + t, liqs + lq, fees + f
            bars = pd.concat(parts, axis=1).fillna(0.0).sum(axis=1)
            blocks = bars.resample("12h").sum()
            wk = bars.resample("W-MON", label="left", closed="left").sum()
            label = f"{name} buffer {buf:.0f}"
            weekly[label] = wk
            eq = blocks.cumsum()
            recent = blocks[blocks.index > blocks.index[-1] - pd.Timedelta(weeks=RECENT_WEEKS)]
            print(
                f"{label:<14}{bars.sum():>10,.0f}{recent.sum():>12,.0f}{trades:>8}"
                f"{trades / len(wk):>9.1f}{fees:>9,.0f}{liqs:>6}{(blocks > 0).mean() * 100:>7.0f}%"
                f"{blocks.min():>10,.0f}{(eq - eq.cummax()).min():>10,.0f}"
            )
    last = pd.DataFrame(weekly).iloc[-8:].round(0)
    last.index = [d.date() for d in last.index]
    print("\nlast 8 weeks (week starting Monday; the last is partial):")
    print(last.to_string())
    print("\nExploratory replay on past prices; not a forecast.")


if __name__ == "__main__":
    main()
