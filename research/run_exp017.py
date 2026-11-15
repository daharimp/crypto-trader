"""EXP-2026-017: regime-switching signal vs the 1-month trend rule (plan: research/EXP-2026-017-plan.md).

Research only; changes no configuration. Replays 30-day TSMOM, a 20-bar mean-reversion rule,
and REGIME (TSMOM while the 30-day efficiency ratio is above its trailing 365-day median,
mean reversion otherwise) at the assessed opening leverage (ADR-032) on one coin at a time,
on a constant $2,500. Panel A: BTC/ETH/SOL with Deribit funding. Panel B: DOGE/LTC/LINK/AVAX/
ADA with Hyperliquid funding.

Usage: uv run python research/run_exp017.py
Needs data/long/<coin>_usd_4h.csv and data/funding/{deribit,hyperliquid}_<coin>.csv.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from run_exp013 import CAPITAL, boot

from trader.perps.leverage_replay import (
    MONTH,
    Replay,
    Venue,
    assessed_leverage,
    daily_move,
    replay,
)
from trader.research.funding import HOURS_PER_BAR, load_funding
from trader.research.lab import BARS_PER_YEAR, load_csv

YEAR = 2190  # 365 days of 4h bars
# Reason: the regime cut needs a year of 30-day efficiency ratios, so every rule starts here.
WARMUP = YEAR + MONTH + 1
PANELS = {
    "A": ("deribit", ("btc", "eth", "sol"), WARMUP),
    "B": ("hyperliquid", ("doge", "ltc", "link", "avax", "ada"), WARMUP),
}
SEED = 17
FUNDED = Venue()
BORROW = Venue(borrow_per_bar=0.0016 / 100 * HOURS_PER_BAR)  # paper session value (UD-28)
RULES = ("TSMOM", "MEANREV", "REGIME")
HEADER = (
    f"{'signal':<11}{'$/yr':>8}{'90% range':>19}{'worst yr':>10}{'max drop':>10}{'$/yr per $ drop':>17}"
    f"{'trades':>8}{'liqs':>6}{'in market':>11}{'avg lev':>9}{'funding $/yr':>14}"
)


def trending(close: pd.Series) -> pd.Series:
    """True where the 30-day efficiency ratio is above its median over the previous year."""
    path = close.diff().abs().rolling(MONTH).sum()
    er = (close - close.shift(MONTH)).abs() / path
    # Reason: shift(1) keeps the cut on past ratios only; the bar itself is not in its median.
    cut = er.shift(1).rolling(YEAR).median()
    return (er > cut) & cut.notna()


def signals(close: pd.Series) -> dict[str, pd.Series]:
    """Desired side after each close for the three rules (+1 long, -1 short, 0 flat)."""
    tsmom = np.sign(close.pct_change(MONTH)).fillna(0.0)
    mean, std = close.rolling(20).mean(), close.rolling(20).std()
    z = (close - mean) / std
    meanrev = pd.Series(np.select([z > 1, z < -1], [-1.0, 1.0], 0.0), index=close.index)
    regime = tsmom.where(trending(close), meanrev)
    return {"TSMOM": tsmom, "MEANREV": meanrev, "REGIME": regime}


def per_year(pnl: np.ndarray) -> float:
    """Average dollars per year."""
    return float(pnl.mean() * BARS_PER_YEAR)


def block(
    label: str, df: pd.DataFrame, funding: pd.Series, venue: Venue, a: int, b: int
) -> tuple[dict[str, float], dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    """Print one table and the paired differences; return averages and 90% ranges."""
    print(f"\n--- {label} ---")
    print(HEADER)
    rng = np.random.default_rng(SEED)
    idx = df.index[a:b]
    lev = assessed_leverage(daily_move(df["close"]), 4.0, venue)
    runs: dict[str, Replay] = {}
    mean: dict[str, float] = {}
    own: dict[str, tuple[float, float]] = {}
    for name, direction in signals(df["close"]).items():
        r = replay(df, direction, lev, funding, venue, a, b)
        runs[name], mean[name] = r, per_year(r.pnl)
        own[name] = boot(r.pnl / CAPITAL, rng)
        years = pd.Series(r.pnl, index=idx).groupby(idx.year).sum()
        cum = np.r_[0.0, np.cumsum(r.pnl)]
        drop = float((np.maximum.accumulate(cum) - cum).max())
        held = float((direction.shift(1).iloc[a:b] != 0).mean() * 100)
        avg = float(np.mean([t["lev"] for t in r.trades])) if r.trades else 0.0
        lo, hi = own[name]
        print(
            f"{name:<11}{mean[name]:>8,.0f}{f'{lo:,.0f} to {hi:,.0f}':>19}{years.min():>10,.0f}"
            f"{drop:>10,.0f}{mean[name] / drop if drop else 0.0:>17.2f}{len(r.trades):>8}"
            f"{r.liquidations:>6}{held:>10.0f}%{avg:>9.1f}{-per_year(r.funding):>14,.0f}"
        )
    diffs: dict[str, tuple[float, float]] = {}
    d = runs["REGIME"].pnl - runs["TSMOM"].pnl
    diffs["TSMOM"] = boot(d / CAPITAL, rng)
    lo, hi = diffs["TSMOM"]
    share = float(trending(df["close"]).iloc[a:b].mean() * 100)
    print(
        f"REGIME minus TSMOM, $/yr with 90% range: {per_year(d):>7,.0f}  ({lo:,.0f} to {hi:,.0f})"
    )
    print(f"bars counted as trending: {share:.0f}%")
    return mean, own, diffs


def main() -> None:
    """Print provenance, both panels, then the decision."""
    print("=== Data files (rows, first, last, sha256) ===")
    for source, coins, _ in PANELS.values():
        for c in coins:
            for path in (f"data/long/{c}_usd_4h.csv", f"data/funding/{source}_{c}.csv"):
                lines = Path(path).read_text(encoding="utf-8").splitlines()
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                first, last = lines[1].split(",")[0], lines[-1].split(",")[0]
                print(f"  {path}: {len(lines) - 1} rows, {first} to {last}, {digest}")

    res: dict[str, dict[str, tuple[dict[str, float], dict, dict]]] = {"A": {}, "B": {}}
    for panel, (source, coins, warmup) in PANELS.items():
        for coin in coins:
            df = load_csv(f"data/long/{coin}_usd_4h.csv")
            hourly = load_funding(f"data/funding/{source}_{coin}.csv")
            hours = [hourly.reindex(df.index + pd.Timedelta(hours=h)) for h in range(HOURS_PER_BAR)]
            known = np.flatnonzero(sum(h.notna().to_numpy() for h in hours) == HOURS_PER_BAR)
            # Reason: the last candle has no next open, so its result is not known yet.
            a, b = max(warmup, int(known[0])), min(int(known[-1]), len(df) - 2) + 1
            partial = int(sum(h.iloc[a:b].isna().to_numpy() for h in hours).astype(bool).sum())
            funding = pd.Series(sum(h.fillna(0.0).to_numpy() for h in hours), index=df.index)
            print(
                f"\n=== Panel {panel}: {coin.upper()} {df.index[a].date()} to {df.index[b - 1].date()}, "
                f"{b - a} bars, {partial} with a missing funding hour ==="
            )
            res[panel][coin] = block(f"PRIMARY: {source} funding", df, funding, FUNDED, a, b)
            zero = pd.Series(0.0, index=df.index)
            block("context: paper session's 0.0016%/h borrow (UD-28)", df, zero, BORROW, a, b)

    print("\n=== Decision (primary cost; rule fixed in the plan) ===")
    a_res, b_res = res["A"], res["B"]
    up = sum(r[2]["TSMOM"][0] > 0 for r in a_res.values())
    down = sum(r[2]["TSMOM"][1] < 0 for r in a_res.values())
    at_least = sum(r[0]["REGIME"] >= r[0]["TSMOM"] for r in b_res.values())
    below = sum(r[0]["REGIME"] < r[0]["TSMOM"] for r in b_res.values())
    print(f"Panel A, REGIME minus TSMOM range above $0 on {up}/3, below $0 on {down}/3")
    print(f"Panel B, REGIME average at least TSMOM's on {at_least}/5, below on {below}/5")
    supported = up >= 2 and at_least >= 3
    contradicted = down >= 2 or below >= 4
    print(
        "VERDICT: "
        + ("supported" if supported else "contradicted" if contradicted else "not settled")
    )


if __name__ == "__main__":
    main()
