"""EXP-2026-015: how should opening leverage be chosen? (plan: research/EXP-2026-015-plan.md)

Research only; changes no configuration. Replays fixed, volatility-assessed, and
volatility-plus-signal-strength opening leverage on one market at a time, on a constant
$2,500 ($250 collateral per trade), with Deribit funding as the holding cost.

Usage: uv run python research/run_exp015.py
Needs the EXP-2026-014 data files (data/long/*_usd_4h.csv, data/funding/deribit_*.csv).
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
    agreement,
    assessed_leverage,
    buffer_for,
    daily_move,
    replay,
    trend_strength,
)
from trader.research.funding import HOURS_PER_BAR, load_funding
from trader.research.lab import BARS_PER_YEAR, load_csv

COINS = ("btc", "eth", "sol")
SEED = 15
RESAMPLES = 2000
FUNDED = Venue()
BORROW = Venue(borrow_per_bar=0.01 / 100 * HOURS_PER_BAR)  # the paper session's 0.01%/h
VS = ("VS1-raise", "VS1-tilt", "VS2-raise", "VS2-tilt")
HEADER = (
    f"{'policy':<11}{'$/yr':>8}{'90% range':>19}{'worst yr':>10}{'max drop':>10}{'trades':>8}"
    f"{'liqs':>6}{'liq $/yr':>10}{'avg lev':>9}{'funding $/yr':>14}"
)


def policies(close: pd.Series, direction: pd.Series) -> dict[str, pd.Series]:
    """Opening leverage per bar for every pre-registered policy."""
    move = daily_move(close)
    z = trend_strength(close)
    agree = agreement(close, direction)
    s1 = (z >= 1.0, z < 0.5)
    s2 = (agree == 1.0, agree == -1.0)
    out = {f"F{x}": pd.Series(float(x), index=close.index) for x in (3, 6, 12, 25)}
    out["V"] = assessed_leverage(move, 4.0, FUNDED)
    for name, (strong, weak) in (("VS1", s1), ("VS2", s2)):
        for kind in ("raise", "tilt"):
            buf = buffer_for(strong, weak, tilt=kind == "tilt")
            out[f"{name}-{kind}"] = assessed_leverage(move, buf, FUNDED)
    return out


def per_year(pnl: np.ndarray) -> float:
    """Average dollars per year."""
    return float(pnl.mean() * BARS_PER_YEAR)


def block(
    label: str,
    df: pd.DataFrame,
    direction: pd.Series,
    funding: pd.Series,
    venue: Venue,
    a: int,
    b: int,
) -> tuple[dict[str, Replay], dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    """Print one table and the paired differences; return replays and 90% ranges."""
    print(f"\n--- {label} ---")
    print(HEADER)
    rng = np.random.default_rng(SEED)
    idx = df.index[a:b]
    runs: dict[str, Replay] = {}
    own: dict[str, tuple[float, float]] = {}
    for name, lev in policies(df["close"], direction).items():
        r = replay(df, direction, lev, funding, venue, a, b)
        runs[name] = r
        lo, hi = boot(r.pnl / CAPITAL, rng)
        own[name] = (lo, hi)
        years = pd.Series(r.pnl, index=idx).groupby(idx.year).sum()
        cum = np.cumsum(r.pnl)
        drop = float((np.maximum.accumulate(np.r_[0.0, cum]) - np.r_[0.0, cum]).max())
        span_years = len(r.pnl) / BARS_PER_YEAR
        liq_usd = sum(-t["pnl"] for t in r.trades if t["liquidated"]) / span_years
        avg = float(np.mean([t["lev"] for t in r.trades])) if r.trades else 0.0
        print(
            f"{name:<11}{per_year(r.pnl):>8,.0f}{f'{lo:,.0f} to {hi:,.0f}':>19}{years.min():>10,.0f}"
            f"{drop:>10,.0f}{len(r.trades):>8}{r.liquidations:>6}{liq_usd:>10,.0f}{avg:>9.1f}"
            f"{-per_year(r.funding):>14,.0f}"
        )
    diffs: dict[str, tuple[float, float]] = {}
    print("differences, $/yr with 90% range:")
    for x, y in [("V", "F12")] + [(v, "V") for v in VS]:
        d = runs[x].pnl - runs[y].pnl
        lo, hi = boot(d / CAPITAL, rng)
        diffs[x] = (lo, hi)
        print(f"  {x} minus {y}: {per_year(d):>7,.0f}  ({lo:,.0f} to {hi:,.0f})")
    return runs, own, diffs


def diagnostic(
    run: Replay, close: pd.Series, direction: pd.Series, rng: np.random.Generator
) -> None:
    """Under V: result per $100 of position, strong-signal trades against the rest."""
    z = trend_strength(close).to_numpy()
    agree = agreement(close, direction).to_numpy()
    per100 = np.array([t["pnl"] / t["size"] * 100 for t in run.trades])
    # Reason: a trade filled at bar i was decided at the close of bar i-1.
    decided = np.array([int(t["bar"]) - 1 for t in run.trades])
    for label, strong in (
        ("S1 trend strength", z[decided] >= 1.0),
        ("S2 agreement", agree[decided] == 1.0),
    ):
        s, w = per100[strong], per100[~strong]
        if len(s) < 2 or len(w) < 2:
            print(f"  {label}: too few trades to compare ({len(s)} strong, {len(w)} other)")
            continue
        draws = [
            rng.choice(s, len(s)).mean() - rng.choice(w, len(w)).mean() for _ in range(RESAMPLES)
        ]
        lo, hi = np.percentile(draws, [5, 95])
        print(
            f"  {label}: strong {s.mean():+.2f} per $100 of position ({len(s)} trades), other "
            f"{w.mean():+.2f} ({len(w)}); difference {s.mean() - w.mean():+.2f} ({lo:+.2f} to {hi:+.2f})"
        )


def main() -> None:
    """Print provenance, one section per coin, then the decisions."""
    print("=== Data files (rows, first, last, sha256) ===")
    for path in [f"data/long/{c}_usd_4h.csv" for c in COINS] + [
        f"data/funding/deribit_{c}.csv" for c in COINS
    ]:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        print(
            f"  {path}: {len(lines) - 1} rows, {lines[1].split(',')[0]} to {lines[-1].split(',')[0]}, {digest}"
        )

    q1: dict[str, tuple[float, float]] = {}
    q2: dict[str, dict[str, tuple[float, float]]] = {v: {} for v in VS}
    worth: dict[str, dict[str, tuple[float, float]]] = {}
    for coin in COINS:
        df = load_csv(f"data/long/{coin}_usd_4h.csv")
        close = df["close"]
        hourly = load_funding(f"data/funding/deribit_{coin}.csv")
        hours = [hourly.reindex(df.index + pd.Timedelta(hours=h)) for h in range(HOURS_PER_BAR)]
        known = np.flatnonzero(sum(h.notna().to_numpy() for h in hours) == HOURS_PER_BAR)
        # Reason: same window as EXP-2026-014; the last candle has no next open.
        a, b = max(WARMUP, int(known[0])), min(int(known[-1]), len(df) - 2) + 1
        partial = int(sum(h.iloc[a:b].isna().to_numpy() for h in hours).astype(bool).sum())
        # Reason (plan): a path cannot skip a bar, so a bar with a missing hour is charged
        # the hours that exist; the count is reported.
        funding = pd.Series(sum(h.fillna(0.0).to_numpy() for h in hours), index=df.index)
        zero = pd.Series(0.0, index=df.index)
        tsmom = np.sign(close.pct_change(MONTH)).fillna(0.0)
        sma = np.sign(close.rolling(20).mean() - close.rolling(50).mean()).fillna(0.0)
        move = daily_move(close).iloc[a:b]
        print(
            f"\n=== {coin.upper()} {df.index[a].date()} to {df.index[b - 1].date()}, {b - a} bars, "
            f"{partial} with a missing funding hour; typical daily move {move.median() * 100:.1f}% "
            f"(middle half {move.quantile(0.25) * 100:.1f}% to {move.quantile(0.75) * 100:.1f}%) ==="
        )
        runs, own, diffs = block(
            "PRIMARY: 1-month trend, Deribit funding", df, tsmom, funding, FUNDED, a, b
        )
        q1[coin], worth[coin] = diffs["V"], own
        for v in VS:
            q2[v][coin] = diffs[v]
        print("strong-signal trades against the rest, under V:")
        diagnostic(runs["V"], close, tsmom, np.random.default_rng(SEED))
        block(
            "context: 1-month trend, paper session's 0.01%/h borrow", df, tsmom, zero, BORROW, a, b
        )
        block(
            "context: sma_stance 20/50 (today's paper signal), Deribit funding",
            df,
            sma,
            funding,
            FUNDED,
            a,
            b,
        )

    def count(ranges: dict[str, tuple[float, float]]) -> tuple[int, int]:
        return sum(lo > 0 for lo, _ in ranges.values()), sum(hi < 0 for _, hi in ranges.values())

    print("\n=== Decisions (1-month trend, Deribit funding; needs 2 of 3 coins) ===")
    up, down = count(q1)
    verdict = "V beats F12" if up >= 2 else "F12 beats V" if down >= 2 else "not shown either way"
    print(
        f"Q1 volatility-assessed vs fixed 12x: above $0 on {up}/3, below $0 on {down}/3 -> {verdict}"
    )
    passed = {v: count(q2[v])[0] >= 2 for v in VS}
    for v in VS:
        up, down = count(q2[v])
        note = "adds money" if passed[v] else "not shown"
        if passed[v] and v.endswith("raise") and not passed[v.replace("raise", "tilt")]:
            note = "more leverage, not strength (tilt twin does not pass)"
        print(f"Q2 {v} vs V: above $0 on {up}/3, below $0 on {down}/3 -> {note}")
    print("Worth running at all (own 90% range above $0 on >= 2 of 3 coins):")
    for name in worth[COINS[0]]:
        n = sum(worth[c][name][0] > 0 for c in COINS)
        print(f"  {name:<11}{n}/3 -> {'yes' if n >= 2 else 'not shown'}")


if __name__ == "__main__":
    main()
