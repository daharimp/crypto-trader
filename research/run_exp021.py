"""EXP-2026-021: which moving-average lengths, and does a trend-vs-range switch help?

Research only. Same replay as EXP-2026-020 (BTC/ETH/SOL 4h, 1x each, equal weight, stop 2
typical daily moves, next-UTC-day wait, Jupiter fees and borrow). Every rule trades both
ways. Lengths are in 4h candles (6 a day). Picked on 2020-2023, checked on 2024-2026.

Usage: python research/run_exp021.py <dir with btc_4h.csv eth_4h.csv sol_4h.csv>
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_exp020 import BORROW_H, COINS, features, load, replay, stats  # noqa: E402

DEV, HOLD = ("2020-01-01", "2024-01-01"), ("2024-01-01", "2026-12-01")
FASTS, SLOWS = (10, 20, 30, 50), (50, 100, 150, 200, 300)


def ma(c: pd.Series, n: int, kind: str) -> pd.Series:
    return (
        c.rolling(n).mean() if kind == "SMA" else c.ewm(span=n, adjust=False, min_periods=n).mean()
    )


def cross_side(c: pd.Series, fast: int, slow: int, kind: str) -> pd.Series:
    f, s = ma(c, fast, kind), ma(c, slow, kind)
    side = pd.Series(np.where(f > s, 1.0, -1.0), index=c.index)
    side[s.isna()] = 0
    return side


def adx(df: pd.DataFrame, n: int) -> pd.Series:
    h, lo, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -lo.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    a = 1 / n
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=a, adjust=False).mean()


def efficiency(c: pd.Series, n: int) -> pd.Series:
    """Kaufman efficiency ratio: net move / path length over n bars (0 = chop, 1 = straight)."""
    return (c - c.shift(n)).abs() / c.diff().abs().rolling(n).sum()


def run(dfs, feats, sides: dict[str, pd.Series]) -> tuple[dict, dict]:
    rets, trades = [], []
    for k in COINS:
        r, t = replay(dfs[k], feats[k], sides[k], BORROW_H["base"])
        rets.append(r)
        trades += t
    port = pd.concat(rets, axis=1).fillna(0).mean(axis=1)
    return stats(port, trades, *DEV), stats(port, trades, *HOLD)


def row(name: str, d: dict, h: dict) -> str:
    return (
        f"{name:34s}{d['cagr'] * 100:7.1f}%{d['sharpe']:6.2f}{d['dd'] * 100:6.0f}%{d['per_mo']:5.1f} |"
        f"{h['cagr'] * 100:7.1f}%{h['sharpe']:6.2f}{h['dd'] * 100:6.0f}%{h['per_mo']:5.1f}"
    )


HEAD = f"{'rule':34s}{'CAGR':>8s}{'Shrp':>6s}{'DD':>7s}{'/mo':>5s} |{'CAGR':>8s}{'Shrp':>6s}{'DD':>7s}{'/mo':>5s}"


def main(data_dir: Path) -> None:
    dfs = {k: load(data_dir / f"{k}_4h.csv") for k in COINS}
    feats = {k: features(v) for k, v in dfs.items()}
    print("EXP-2026-021 moving-average lengths and a trend-vs-range switch. Long and short, 1x.")
    print("Lengths in 4h candles (6 a day: 50 = 8 days, 200 = 33 days, 300 = 50 days).")
    print("Left: development 2020-2023 (used to pick). Right: holdout 2024-2026 (not used).\n")

    # 1) Grid of crossover lengths, SMA and EMA.
    grid = []
    for kind, fast, slow in itertools.product(("SMA", "EMA"), FASTS, SLOWS):
        if fast >= slow:
            continue
        sides = {k: cross_side(dfs[k]["close"], fast, slow, kind) for k in COINS}
        d, h = run(dfs, feats, sides)
        grid.append((f"{kind} {fast}/{slow}", d, h))
    grid.sort(key=lambda x: -x[1]["sharpe"])
    print("== 1. every crossover, both ways, sorted by development Sharpe")
    print(HEAD)
    for name, d, h in grid:
        print(row(name, d, h))
    dev_rank = pd.Series({n: d["sharpe"] for n, d, _ in grid}).rank()
    hold_rank = pd.Series({n: h["sharpe"] for n, _, h in grid}).rank()
    print(
        f"\nrank correlation, development Sharpe vs holdout Sharpe: {dev_rank.corr(hold_rank):.2f}"
    )
    top = [n for n, _, _ in grid[:5]]
    print(
        f"top 5 picked on development: {', '.join(top)}; their mean holdout Sharpe "
        f"{np.mean([h['sharpe'] for n, _, h in grid[:5]]):.2f} vs all {np.mean([h['sharpe'] for _, _, h in grid]):.2f}\n"
    )

    # 2) Trend-vs-range switches on top of 50/200 SMA (current) and the best development pair.
    best = grid[0][0].split()
    base_kind, (bf, bs) = best[0], map(int, best[1].split("/"))
    print(
        f"== 2. trend-vs-range switches (range = weak trend measure); base pairs SMA 50/200 and {grid[0][0]}"
    )
    print(HEAD)
    adxs = {k: adx(dfs[k], 14 * 6) for k in COINS}  # 14-day ADX on 4h bars
    ers = {k: efficiency(dfs[k]["close"], 30 * 6) for k in COINS}  # 30-day efficiency
    for kind, f_, s_ in (("SMA", 50, 200), (base_kind, bf, bs)):
        slow_sides = {k: cross_side(dfs[k]["close"], f_, s_, kind) for k in COINS}
        fast_sides = {k: cross_side(dfs[k]["close"], 10, 30, kind) for k in COINS}
        d, h = run(dfs, feats, slow_sides)
        print(row(f"{kind} {f_}/{s_} plain", d, h))
        for meas, vals, ths in (("ADX", adxs, (15, 20, 25)), ("ER", ers, (0.05, 0.1, 0.15))):
            for th in ths:
                flat = {k: slow_sides[k].where(vals[k] >= th, 0.0) for k in COINS}
                d, h = run(dfs, feats, flat)
                print(row(f"  {meas}<{th}: sit out", d, h))
                swap = {k: slow_sides[k].where(vals[k] >= th, fast_sides[k]) for k in COINS}
                d, h = run(dfs, feats, swap)
                print(row(f"  {meas}<{th}: switch to {kind} 10/30", d, h))
        print()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
