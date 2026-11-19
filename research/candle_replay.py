"""Candle replay: a decision at EVERY 4h close, from how that candle closed.

EXPLORATORY (owner request, 2026-11-15: "a trade based on how a candle on the 4 closes EVERY
time", as well as the trend trade). Every input below was fixed in this file and committed
before any result was computed. Research only; changes no configuration. Buffers other than
4 are TEST INPUTS, not approved values.

Rule, at each 4h close, per coin:
- FOLLOW: the candle closed up (close above open) -> be long for the next 4 hours; closed
  down -> be short. If the new candle points the same way, the position stays open (no
  extra fees); if it flips, close and reverse at the next open.
- FADE: the mirror (closed up -> short), shown so the direction is not cherry-picked.
- Leverage as the running rule: 4 typical daily moves of buffer (FOLLOW, FADE), and 2 daily
  moves for FOLLOW2 (degen test input). 1x to 25x, liquidation at least 3.5% away (UD-27).
- $250 collateral per trade per coin; 7 bps fee per side; 20 bps maintenance; Deribit funding.

Shown next to the running trend account (RUNNING) and both together (RUNNING+FOLLOW: two
separate $250 positions per coin), in 12-hour blocks and weeks.

Usage: uv run python research/candle_replay.py
Needs data/long/<coin>_usd_4h.csv and data/funding/deribit_<coin>.csv.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from bigger_bets_replay import COINS, NY, RECENT_WEEKS, SHOW_DAYS, row
from degen_replay import VENUE, floored

from trader.perps.leverage_replay import assessed_leverage, replay
from trader.research.funding import load_funding, per_bar
from trader.research.lab import load_csv


def coin_runs(coin: str, start: pd.Timestamp) -> dict[str, tuple[pd.Series, int, float, int]]:
    """Per variant: dollars per 4h bar, liquidations, average leverage, trade count."""
    df4 = load_csv(f"data/long/{coin}_usd_4h.csv")
    fund = per_bar(load_funding(f"data/funding/deribit_{coin}.csv"), df4.index)
    c = df4["close"]
    candle = np.sign(c - df4["open"]).fillna(0.0)
    trend = np.sign(c.pct_change(180)).fillna(0.0)
    move = c.pct_change().rolling(180).std() * math.sqrt(6)
    lev4 = floored(assessed_leverage(move, 4.0, VENUE))
    lev2 = floored(assessed_leverage(move, 2.0, VENUE))
    a, b = int(df4.index.searchsorted(start)), len(df4) - 1
    variants = {
        "RUNNING": (trend, lev4),
        "FOLLOW": (candle, lev4),
        "FADE": (-candle, lev4),
        "FOLLOW2": (candle, lev2),
    }
    out = {}
    for name, (side, lev) in variants.items():
        r = replay(df4, side, lev, fund, VENUE, a, b)
        avg = float(np.mean([t["lev"] for t in r.trades])) if r.trades else 0.0
        out[name] = (pd.Series(r.pnl, index=df4.index[a:b]), r.liquidations, avg, len(r.trades))
    return out


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
    bars["RUNNING+FOLLOW"] = bars["RUNNING"] + bars["FOLLOW"]
    print(
        f"Whole account from {start.date()} (4h bars, open time); 12h blocks start 00:00/12:00 UTC."
    )
    for n in names:
        t = sum(runs[c][n][3] for c in COINS)
        weeks = len(bars[n]) / 42
        print(f"  {n}: {t} trades ({t / weeks:.1f} a week across the 3 coins)")
    print(
        f"\n{'':<22}{'total $':>10}{'12h up':>8}{'med 12h':>8}{'best 12h':>9}{'worst 12h':>9}"
        f"{'wks up':>8}{'worst wk':>9}{'max drop':>10}{'liqs':>6}{'lev':>6}"
    )
    blocks = {n: s.resample("12h").sum() for n, s in bars.items()}
    weeks = {n: s.resample("W-MON", label="left", closed="left").sum() for n, s in bars.items()}
    recent = blocks["RUNNING"].index[-1] - pd.Timedelta(weeks=RECENT_WEEKS)
    for n in bars:
        liqs = sum(runs[c][n][1] for c in COINS) if n in names else 0
        lev = float(np.mean([runs[c][n][2] for c in COINS])) if n in names else 0.0
        b, w = blocks[n], weeks[n]
        print(row(f"{n} all", b, w, liqs, lev))
        print(
            row(f"{n} last {RECENT_WEEKS} wks", b[b.index > recent], w[w.index > recent], 0, 0)[
                :-12
            ]
        )

    table = pd.DataFrame(blocks).round(0)
    table.index = [t.tz_convert(NY).strftime("%a %b %d %I%p ET") for t in table.index]
    print(f"\nwhole account, last {SHOW_DAYS} days in 12-hour blocks (block start, New York time):")
    print(table.iloc[-SHOW_DAYS * 2 :].to_string())
    print(f"\nrunning total over the last {SHOW_DAYS} days:")
    print(table.iloc[-SHOW_DAYS * 2 :].cumsum().to_string())
    print(f"\nwhole account, last {RECENT_WEEKS} weeks in 12-hour blocks:")
    print(table.iloc[-RECENT_WEEKS * 14 :].to_string())
    print("\nExploratory replay on past prices with test inputs; not a forecast.")


if __name__ == "__main__":
    main()
