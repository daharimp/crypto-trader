"""EXP-2026-016: consensus signal vs each rule alone (plan: research/EXP-2026-016-plan.md).

Research only; changes no configuration. Replays SMA 20/50, 30-day TSMOM, and their consensus
at the assessed opening leverage (ADR-032) on one coin at a time, on a constant $2,500.
Panel A: BTC/ETH/SOL with Deribit funding. Panel B: five coins never looked at before, with
Hyperliquid funding.

Usage: uv run python research/run_exp016.py
Needs data/long/<coin>_usd_4h.csv and data/funding/{deribit,hyperliquid}_<coin>.csv.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from run_exp013 import CAPITAL, WARMUP, boot

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

PANELS = {
    "A": ("deribit", ("btc", "eth", "sol"), WARMUP),
    # Reason: 30 days of bars is the longest warm-up any signal or the volatility needs.
    "B": ("hyperliquid", ("doge", "ltc", "link", "avax", "ada"), MONTH + 1),
}
SEED = 16
FUNDED = Venue()
BORROW = Venue(borrow_per_bar=0.0016 / 100 * HOURS_PER_BAR)  # paper session value (UD-28)
RULES = ("SMA", "TSMOM", "CONSENSUS")
HEADER = (
    f"{'signal':<11}{'$/yr':>8}{'90% range':>19}{'worst yr':>10}{'max drop':>10}{'$/yr per $ drop':>17}"
    f"{'trades':>8}{'liqs':>6}{'in market':>11}{'avg lev':>9}{'funding $/yr':>14}"
)


def signals(close: pd.Series) -> dict[str, pd.Series]:
    """Desired side after each close for the three rules (+1 long, -1 short, 0 flat)."""
    sma = np.sign(close.rolling(20).mean() - close.rolling(50).mean()).fillna(0.0)
    tsmom = np.sign(close.pct_change(MONTH)).fillna(0.0)
    # Reason: the consensus takes a side only when both rules name the same one.
    return {"SMA": sma, "TSMOM": tsmom, "CONSENSUS": sma.where(sma == tsmom, 0.0)}


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
    print("differences, $/yr with 90% range:")
    for other in ("SMA", "TSMOM"):
        d = runs["CONSENSUS"].pnl - runs[other].pnl
        diffs[other] = boot(d / CAPITAL, rng)
        lo, hi = diffs[other]
        print(f"  CONSENSUS minus {other}: {per_year(d):>7,.0f}  ({lo:,.0f} to {hi:,.0f})")
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

    print("\n=== Decision (primary cost) ===")
    a_res, b_res = res["A"], res["B"]
    beats, beaten = {}, {}
    for other in ("SMA", "TSMOM"):
        up = sum(r[2][other][0] > 0 for r in a_res.values())
        down = sum(r[2][other][1] < 0 for r in a_res.values())
        beats[other], beaten[other] = up >= 2, down >= 2
        verdict = (
            "consensus beats it"
            if up >= 2
            else f"{other} beats consensus"
            if down >= 2
            else "not shown either way"
        )
        print(
            f"Panel A, CONSENSUS vs {other}: above $0 on {up}/3, below $0 on {down}/3 -> {verdict}"
        )
    own_a = sum(r[1]["CONSENSUS"][0] > 0 for r in a_res.values())
    own_b = sum(r[1]["CONSENSUS"][0] > 0 for r in b_res.values())
    at_least = sum(
        all(r[0]["CONSENSUS"] >= r[0][o] for o in ("SMA", "TSMOM")) for r in b_res.values()
    )
    below = {o: sum(r[0]["CONSENSUS"] < r[0][o] for r in b_res.values()) for o in ("SMA", "TSMOM")}
    print(f"Panel A, CONSENSUS own range above $0: {own_a}/3")
    print(f"Panel B, CONSENSUS own range above $0: {own_b}/5")
    print(f"Panel B, CONSENSUS average at least as high as both single rules: {at_least}/5")
    print(
        f"Panel B, CONSENSUS average below SMA on {below['SMA']}/5, below TSMOM on {below['TSMOM']}/5"
    )
    supported = own_a >= 2 and not any(beaten.values()) and at_least >= 3 and own_b >= 3
    contradicted = any(beaten.values()) or any(n >= 4 for n in below.values())
    print(
        "VERDICT: "
        + (
            "supported as the default"
            if supported
            else "contradicted"
            if contradicted
            else "not settled"
        )
    )


if __name__ == "__main__":
    main()
