"""Degen v2 replay: one shared account that follows the volume, with a take-profit ladder.

EXPLORATORY (owner request, 2026-11-15: "follow the volume", "degen mode ... fast and larger
return"). Borrows from the owner's Longatron GPT (take 30-40% at TP1 and move the stop toward
entry; tight stop so the stop comes before liquidation); it is not a copy of it. Every input
below was fixed in this file and committed before any result was computed. Research only;
changes no configuration. All numbers are TEST INPUTS, not approved risk values.

Changes from ``trend_stack_replay.py`` (same direction, checks, stop and trailing exit):
- One account for SOL, BTC and ETH, at most ONE open position at a time (owner: not a
  per-coin thing). Entry also needs a volume spike: the 15M volume at least 2x its 20-bar
  average. When several coins qualify on the same close, take the largest spike.
- $750 collateral per trade (the three coins' $250 pooled), so totals compare with the
  whole-account rows of the earlier replays.
- Leverage from the stop distance, 50% of the collateral lost if stopped (degen), on every
  setup that passes 6 of 7 checks. Cap 25x (the project's ceiling, UD-27); variant CAP40
  tries 40x as a test input only.
- Take-profit ladder: TP1 at 1.5x the stop distance; close 35% there and move the stop to
  entry. The rest trails (15M EMA 9/26 crosses back) or hits the stop. Variant NOLADDER
  drops the ladder to show what it adds.
- Within a bar the stop is checked before TP1 (pessimistic), and a stop moved to entry
  applies from the next bar.
- Costs as before: 7 bps per side on size, 20 bps maintenance, Deribit funding per 15M.

Usage: uv run python research/degen2_replay.py
Needs data/m15/<coin>_usd_15m.csv, data/long/<coin>_usd_4h.csv, data/funding/deribit_<coin>.csv.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from degen_replay import baseline, run
from trend_stack_replay import checks, ema

from trader.research.funding import load_funding, per_bar
from trader.research.lab import load_csv

COINS = ("sol", "btc", "eth")
FEE, MAINT, COLL, SHARE = 0.0007, 0.002, 750.0, 0.50
SPIKE, TP1_R, TP1_PART = 2.0, 1.5, 0.35
VARIANTS = {"DEGEN2": (25.0, True), "CAP40": (40.0, True), "NOLADDER": (25.0, False)}
RECENT_WEEKS = 26


def prepare(coin: str, index: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Per-coin arrays on the shared 15M index: prices, signals, stops, funding."""
    df = load_csv(f"data/m15/{coin}_usd_15m.csv").reindex(index)
    hourly = load_funding(f"data/funding/deribit_{coin}.csv")
    trend, nl, ns = (x.to_numpy() for x in checks(df))
    o, hi, lo, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum(hi - lo, np.maximum(abs(hi - pc), abs(lo - pc)))
    v = df["volume"]
    want = np.where((trend > 0) & (nl >= 6), 1, np.where((trend < 0) & (ns >= 6), -1, 0))
    return {
        "o": o,
        "hi": hi,
        "lo": lo,
        "c": c,
        "want": want,
        "spike": (v / v.rolling(20).mean()).to_numpy(),
        "gap": (ema(df["close"], 9) - ema(df["close"], 26)).to_numpy(),
        "atr": pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy(),
        "swing_lo": pd.Series(lo).rolling(12).min().to_numpy(),
        "swing_hi": pd.Series(hi).rolling(12).max().to_numpy(),
        "fund": np.nan_to_num(hourly.reindex(index.floor("h")).to_numpy(dtype=float) / 4),
    }


def pick(data: dict[str, dict[str, np.ndarray]], i: int) -> str | None:
    """The coin with a valid setup and the largest volume spike at close ``i``, if any."""
    best, best_spike = None, SPIKE
    for coin, d in data.items():
        s = d["spike"][i]
        if d["want"][i] != 0 and np.isfinite(d["atr"][i]) and np.isfinite(s) and s >= best_spike:
            best, best_spike = coin, s
    return best


def hold(
    d: dict[str, np.ndarray], side: int, entry: float, stop: float, lev: float, j: int, ladder: bool
):
    """Hold from bar ``j``; return (exit bar, dollars, reason, tp1 hit)."""
    size = COLL * lev
    liq = entry * (1 - side * (1 / lev - FEE - MAINT))
    tp1 = entry * (1 + side * TP1_R * abs(entry - stop) / entry)
    left, cash, hit, n = 1.0, -size * FEE, False, len(d["o"])
    while True:
        cash -= side * size * left * d["fund"][j]
        adverse = d["lo"][j] if side > 0 else d["hi"][j]
        favour = d["hi"][j] if side > 0 else d["lo"][j]
        if (adverse - liq) * side <= 0 and (d["o"][j] - liq) * side <= 0:
            return j, max(cash - COLL, -COLL), "liquidated", hit
        if (adverse - stop) * side <= 0:
            fill = min(d["o"][j], stop) if side > 0 else max(d["o"][j], stop)
            cash += side * size * left * (fill / entry - 1) - size * left * FEE
            return j, max(cash, -COLL), "stop", hit
        new_stop = stop
        if ladder and not hit and (favour - tp1) * side >= 0:
            fill = max(d["o"][j], tp1) if side > 0 else min(d["o"][j], tp1)
            cash += side * size * TP1_PART * (fill / entry - 1) - size * TP1_PART * FEE
            left, hit, new_stop = 1.0 - TP1_PART, True, entry
        if j + 1 >= n or not np.isfinite(d["o"][j + 1]):
            cash += side * size * left * (d["c"][j] / entry - 1) - size * left * FEE
            return j, max(cash, -COLL), "end", hit
        if d["gap"][j] * side < 0:
            cash += side * size * left * (d["o"][j + 1] / entry - 1) - size * left * FEE
            return j + 1, max(cash, -COLL), "trail", hit
        # Reason: a stop moved to entry inside this bar only applies from the next bar.
        stop, j = new_stop, j + 1


def simulate(data: dict[str, dict[str, np.ndarray]], a: int, cap: float, ladder: bool):
    """One position at a time across coins; return dollars per bar and the trade list."""
    n = len(next(iter(data.values()))["o"])
    pnl, trades, i = np.zeros(n), [], a - 1
    while i < n - 2:
        i += 1
        coin = pick(data, i)
        if coin is None:
            continue
        d = data[coin]
        side = int(d["want"][i])
        raw = d["swing_lo"][i] if side > 0 else d["swing_hi"][i]
        c, atr = d["c"][i], d["atr"][i]
        stop = min(raw, c - atr) if side > 0 else max(raw, c + atr)
        entry = d["o"][i + 1]
        dist = (entry - stop) / entry * side
        if not np.isfinite(dist) or dist <= 0:
            continue
        lev = min(cap, max(1.0, math.floor(SHARE / dist * 10 + 1e-9) / 10))
        j, res, why, hit = hold(d, side, entry, stop, lev, i + 1, ladder)
        pnl[j] += res
        fees = COLL * lev * FEE * 2
        trades.append({"coin": coin, "lev": lev, "pnl": res, "why": why, "tp1": hit, "fees": fees})
        # Reason: a stop fills inside bar j, so the close of j is the next decision; a trail
        # exit fills at the open of j, whose close is likewise the next decision.
        i = j - 1
    return pnl, trades


def mon_weeks(s: pd.Series) -> pd.Series:
    """Dollars per calendar week, Monday 00:00 UTC to Sunday 23:59 UTC."""
    start = s.index.tz_convert("UTC").normalize() - pd.to_timedelta(s.index.day_of_week, unit="D")
    return s.groupby(start).sum()


def stats(label: str, w: pd.Series) -> str:
    """Weekly statistics plus the worst peak-to-trough drop of the running total."""
    eq = w.cumsum()
    dd = float((eq - eq.cummax()).min())
    return (
        f"{label:<24}{len(w):>6}{w.sum():>10,.0f}{w.mean():>8,.0f}{w.median():>8,.0f}"
        f"{(w > 0).mean() * 100:>7.0f}%{w.max():>9,.0f}{w.min():>9,.0f}{dd:>10,.0f}"
    )


def main() -> None:
    """Print the whole-account comparison, trade quality, and the last 26 weeks."""
    frames = {c: load_csv(f"data/m15/{c}_usd_15m.csv") for c in COINS}
    index = frames["sol"].index
    for df in frames.values():
        index = index.intersection(df.index)
    data = {c: prepare(c, index) for c in COINS}
    start = (index[0] + pd.Timedelta(days=40)).ceil("D")
    start += pd.Timedelta(days=(7 - start.day_of_week) % 7)
    a = int(index.searchsorted(start))
    print(
        f"Shared 15M index: {len(index)} bars, replay from {start.date()} ({len(index) - a} bars)"
    )
    print("Weeks run Monday 00:00 UTC to Sunday; the last week is partial.\n")

    weeks: dict[str, pd.Series] = {}
    for name, (cap, ladder) in VARIANTS.items():
        pnl, trades = simulate(data, a, cap, ladder)
        weeks[name] = mon_weeks(pd.Series(pnl[a:], index=index[a:]))
        t = pd.DataFrame(trades)
        print(
            f"{name}: {len(t)} trades ({len(t) / len(weeks[name]):.1f}/week), won "
            f"{(t.pnl > 0).mean() * 100:.0f}%, TP1 hit {t.tp1.mean() * 100:.0f}%, avg lev "
            f"{t.lev.mean():.1f}x, fees ${t.fees.sum():,.0f}, liquidations {(t.why == 'liquidated').sum()}"
        )
        print(
            f"    by coin: {t.coin.value_counts().to_dict()}  exits: {t.why.value_counts().to_dict()}"
        )
    parts = []
    for coin in COINS:
        df4 = load_csv(f"data/long/{coin}_usd_4h.csv")
        fund = per_bar(load_funding(f"data/funding/deribit_{coin}.csv"), df4.index)
        a4 = int(df4.index.searchsorted(start))
        r = run("BASELINE", df4, *baseline(df4), fund, a4)[0]
        parts.append(mon_weeks(pd.Series(r.pnl, index=df4.index[a4 : a4 + len(r.pnl)])))
    weeks["BASELINE"] = pd.concat(parts, axis=1).dropna().sum(axis=1)

    print(
        f"\n{'':<24}{'weeks':>6}{'total $':>10}{'avg wk':>8}{'median':>8}{'win wks':>8}"
        f"{'best wk':>9}{'worst wk':>9}{'max drop':>10}"
    )
    for name, w in weeks.items():
        print(stats(f"{name} all", w))
        print(stats(f"{name} last {RECENT_WEEKS}", w.iloc[-RECENT_WEEKS:]))
    last = pd.DataFrame(weeks).iloc[-RECENT_WEEKS:].round(0)
    last.index = [d.date() for d in last.index]
    print(f"\nwhole account, last {RECENT_WEEKS} weeks (week starting Monday):")
    print(last.to_string())
    print("\nExploratory replay on past prices with test inputs; not a forecast.")


if __name__ == "__main__":
    main()
