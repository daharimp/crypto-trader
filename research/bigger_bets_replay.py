"""Bigger bets on the running rule: smaller liquidation buffer, and leaning in on volume.

EXPLORATORY (owner request, 2026-11-15: "yes run it, show me 12hr by 12hr"). The 15M
replays lost to fees; this keeps the running paper account's signal (4h candles, 30-day
trend, long or short) and only bets bigger. Every input below was fixed in this file and
committed before any result was computed. Research only; changes no configuration. All
buffers other than 4 are TEST INPUTS, not approved values (the approved buffer is 4, UD-26).

Variants (each coin $250 collateral per trade, SOL + BTC + ETH, summed as one account):
- RUNNING: the running rule, 4 typical daily moves of liquidation buffer (UD-26).
- MOVES3, MOVES2: 3 or 2 daily moves of buffer (about 1.3x and 2x the leverage).
- VOLUME: 4 daily moves normally, 2 daily moves when the coin's last 24 hours of volume is
  at least 1.5x its 30-day daily average at the close where the trade opens ("follow the
  volume": bet bigger on the coin where the action is).
All: leverage between 1x and 25x, no open whose liquidation would be closer than 3.5%
(UD-27), 7 bps fee per side, 20 bps maintenance, measured Deribit funding, liquidation on
each bar's adverse extreme, open positions valued at each 4h close.

Reported in 12-hour blocks (00:00-12:00 and 12:00-24:00 UTC, i.e. 7pm-7am and 7am-7pm
New York time in winter), plus weekly totals for context.

Usage: uv run python research/bigger_bets_replay.py
Needs data/long/<coin>_usd_4h.csv and data/funding/deribit_<coin>.csv.
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
SPIKE = 1.5
RECENT_WEEKS = 26
SHOW_DAYS = 14
NY = "America/New_York"


def buffers(df4: pd.DataFrame) -> dict[str, pd.Series | float]:
    """Daily moves of liquidation buffer per variant, decided at each 4h close."""
    day_vol = df4["volume"].rolling(6).sum()
    avg = df4["volume"].rolling(180).sum() / 30
    loud = (day_vol >= SPIKE * avg).fillna(False)
    return {
        "RUNNING": 4.0,
        "MOVES3": 3.0,
        "MOVES2": 2.0,
        "VOLUME": pd.Series(np.where(loud, 2.0, 4.0), index=df4.index),
    }


def coin_runs(coin: str, start: pd.Timestamp) -> dict[str, tuple[pd.Series, int, float]]:
    """Per variant: dollars per 4h bar from ``start``, liquidations, and average leverage."""
    df4 = load_csv(f"data/long/{coin}_usd_4h.csv")
    fund = per_bar(load_funding(f"data/funding/deribit_{coin}.csv"), df4.index)
    c = df4["close"]
    side = np.sign(c.pct_change(180)).fillna(0.0)
    move = c.pct_change().rolling(180).std() * math.sqrt(6)
    a, b = int(df4.index.searchsorted(start)), len(df4) - 1
    out = {}
    for name, buf in buffers(df4).items():
        lev = floored(assessed_leverage(move, buf, VENUE))
        r = replay(df4, side, lev, fund, VENUE, a, b)
        avg = float(np.mean([t["lev"] for t in r.trades])) if r.trades else 0.0
        out[name] = (pd.Series(r.pnl, index=df4.index[a:b]), r.liquidations, avg)
    return out


def row(label: str, blocks: pd.Series, weeks: pd.Series, liqs: int, lev: float) -> str:
    """Summary of 12-hour blocks and weeks, plus the worst peak-to-trough drop."""
    eq = blocks.cumsum()
    dd = float((eq - eq.cummax()).min())
    return (
        f"{label:<22}{blocks.sum():>10,.0f}{(blocks > 0).mean() * 100:>7.0f}%{blocks.median():>8,.0f}"
        f"{blocks.max():>9,.0f}{blocks.min():>9,.0f}{(weeks > 0).mean() * 100:>7.0f}%"
        f"{weeks.min():>9,.0f}{dd:>10,.0f}{liqs:>6}{lev:>6.1f}"
    )


def main() -> None:
    """Print the whole-account comparison and the recent 12-hour blocks."""
    firsts = [load_csv(f"data/long/{c}_usd_4h.csv").index[0] for c in COINS]
    start = (max(firsts) + pd.Timedelta(days=200)).ceil("D")
    start += pd.Timedelta(days=(7 - start.day_of_week) % 7)
    runs = {c: coin_runs(c, start) for c in COINS}
    names = list(runs[COINS[0]])
    bars = {
        n: pd.concat([runs[c][n][0] for c in COINS], axis=1).dropna().sum(axis=1) for n in names
    }
    last = min(s.index[-1] for s in bars.values())
    print(f"Whole account from {start.date()} to {last} UTC (4h bars, open time)")
    print("12h blocks start 00:00 and 12:00 UTC; weeks start Monday 00:00 UTC.\n")
    head = (
        f"{'':<22}{'total $':>10}{'12h up':>8}{'med 12h':>8}{'best 12h':>9}{'worst 12h':>9}"
        f"{'wks up':>8}{'worst wk':>9}{'max drop':>10}{'liqs':>6}{'lev':>6}"
    )
    print(head)
    blocks = {n: s.resample("12h").sum() for n, s in bars.items()}
    weeks = {n: s.resample("W-MON", label="left", closed="left").sum() for n, s in bars.items()}
    recent = blocks[names[0]].index[-1] - pd.Timedelta(weeks=RECENT_WEEKS)
    for n in names:
        liqs = sum(runs[c][n][1] for c in COINS)
        lev = float(np.mean([runs[c][n][2] for c in COINS]))
        b, w = blocks[n], weeks[n]
        print(row(f"{n} all", b, w, liqs, lev))
        print(
            row(f"{n} last {RECENT_WEEKS} wks", b[b.index > recent], w[w.index > recent], 0, 0)[
                :-12
            ]
        )

    table = pd.DataFrame(blocks).round(0)
    table.index = [t.tz_convert(NY).strftime("%a %b %d %I%p ET") for t in table.index]
    print(
        f"\nwhole account, last {RECENT_WEEKS} weeks in 12-hour blocks (block start, New York time):"
    )
    print(table.iloc[-RECENT_WEEKS * 14 :].to_string())
    cum = table.iloc[-SHOW_DAYS * 2 :].cumsum()
    print(f"\nrunning total over the last {SHOW_DAYS} days:")
    print(cum.to_string())
    print("\nExploratory replay on past prices with test inputs; not a forecast.")


if __name__ == "__main__":
    main()
