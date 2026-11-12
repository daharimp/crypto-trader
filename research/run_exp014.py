"""EXP-2026-014: the EXP-2026-013 trials with real funding (plan: research/EXP-2026-014-plan.md).

Research only. Re-runs the eight pre-registered trials unchanged, replacing the assumed
holding cost with measured hourly perps funding. Deribit decides (longest history);
Hyperliquid and Kraken Futures are cross-checks. Dollars are on a constant $2,500.

Usage: uv run python research/run_exp014.py
Needs data/long/{btc,eth,sol}_usd_4h.csv (scripts/fetch_coinbase_history.py) and
data/funding/{deribit,hyperliquid,kraken}_{btc,eth,sol}.csv (scripts/fetch_funding_history.py).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from run_exp013 import CAPITAL, PAIRS, TRIALS, WARMUP, boot, per_year

from trader.research.funding import load_funding, per_bar, simulate_funded
from trader.research.lab import BARS_PER_YEAR, PERPS, Costs, load_csv, simulate

COINS = ("btc", "eth", "sol")
PRIMARY = "deribit"
SOURCES = (PRIMARY, "hyperliquid", "kraken")
FEE_BPS = PERPS.fee_bps_per_side
MAX_DROPPED = 0.01
SEED = 14
HEADER = (
    f"{'trial':<22}{'$/yr':>8}{'90% range':>18}{'worst yr':>10}{'up yrs':>9}"
    f"{'down yrs':>10}{'max DD':>8}{'funding $/yr':>14}"
)


def dollars(r: pd.Series) -> float:
    """Average dollars per year on the constant capital."""
    return float(r.mean() * BARS_PER_YEAR * CAPITAL)


def table(
    rows: list[tuple[str, pd.Series, float | None]], up: pd.Series, rng: np.random.Generator
) -> dict[str, tuple[float, float]]:
    """Print one line per row and return each row's 90% range keyed by its first two letters."""
    print(HEADER)
    ranges: dict[str, tuple[float, float]] = {}
    for name, r, funding in rows:
        yrs = per_year(r)
        eq = (1 + r).cumprod()
        lo, hi = boot(r.to_numpy(), rng)
        ranges[name[:2]] = (lo, hi)
        fund = "" if funding is None else f"{funding:,.0f}"
        print(
            f"{name:<22}{dollars(r):>8,.0f}{f'{lo:,.0f} to {hi:,.0f}':>18}{yrs.min():>10,.0f}"
            f"{yrs[up].mean():>9,.0f}{yrs[~up].mean():>10,.0f}"
            f"{(1 - eq / eq.cummax()).max() * 100:>7.0f}%{fund:>14}"
        )
    return ranges


def pairs(
    rets: dict[str, pd.Series], rng: np.random.Generator
) -> dict[tuple[str, str], tuple[float, float, float]]:
    """Print and return (mean, low, high) of long+short minus long-only for each pair."""
    out = {}
    print("short side added (L+S minus L), $/yr with 90% range:")
    for a, b in PAIRS:
        d = rets[a] - rets[b]
        lo, hi = boot(d.to_numpy(), rng)
        out[(a, b)] = (dollars(d), lo, hi)
        print(f"  {a} vs {b}: {dollars(d):>7,.0f}  ({lo:,.0f} to {hi:,.0f})")
    return out


def main() -> None:
    """Print data provenance, one block per coin and source, then the decision."""
    print("=== Data files (rows, first, last, sha256) ===")
    files = [f"data/long/{c}_usd_4h.csv" for c in COINS]
    files += [f"data/funding/{s}_{c}.csv" for s in SOURCES for c in COINS]
    for path in files:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        first, last = lines[1].split(",")[0], lines[-1].split(",")[0]
        print(f"  {path}: {len(lines) - 1} rows, {first} to {last}, {digest}")

    # cond[pair][coin] = (short side adds, long+short itself above $0, own lower bound)
    cond: dict[tuple[str, str], dict[str, tuple[bool, bool, float]]] = {p: {} for p in PAIRS}
    cross: dict[tuple[str, str], list[str]] = {p: [] for p in PAIRS}
    for coin in COINS:
        df = load_csv(f"data/long/{coin}_usd_4h.csv")
        targets = {name: sig(df) for name, sig in TRIALS.items()}
        for source in SOURCES:
            hourly = load_funding(f"data/funding/{source}_{coin}.csv")
            bar = per_bar(hourly, df.index)
            known = np.flatnonzero(bar.notna().to_numpy())
            # Reason: the last candle has no next open, so its return is not known yet.
            a, b = max(WARMUP, int(known[0])), min(int(known[-1]), len(df) - 2) + 1
            keep = bar.iloc[a:b].notna()
            dropped = int((~keep).sum())
            span = f"{df.index[a].date()} to {df.index[b - 1].date()}"
            role = "PRIMARY" if source == PRIMARY else "cross-check"
            print(f"\n=== {coin.upper()} {span}, {source} funding ({role}), $2,500 constant ===")
            window = hourly[df.index[a] : df.index[b - 1] + pd.Timedelta(hours=3)]
            print(
                f"funding in window: average {window.mean() * 8760 * 100:+.1f}% of position size "
                f"per year (positive: longs pay shorts); positive in {(window > 0).mean() * 100:.0f}% "
                f"of hours; {len(keep)} bars, {dropped} dropped for missing hours"
            )
            if dropped > MAX_DROPPED * len(keep):
                print("UNUSABLE: more than 1% of bars lack funding; not patched, not evaluated")
                continue
            bh = (df["open"].shift(-1) / df["open"] - 1).iloc[a:b][keep]
            up = per_year(bh) > 0
            rng = np.random.default_rng(SEED)
            rets: dict[str, pd.Series] = {}
            rows: list[tuple[str, pd.Series, float | None]] = [("BH buy and hold", bh, None)]
            for name, target in targets.items():
                r = simulate_funded(df, target, FEE_BPS, bar).iloc[a:b][keep]
                pos = target.shift(1).fillna(0.0).iloc[a:b][keep]
                rets[name[:2]] = r
                rows.append((name, r, dollars(-pos * bar.iloc[a:b][keep])))
            own = table(rows, up, rng)
            diffs = pairs(rets, rng)
            for pair, (mean, lo, _hi) in diffs.items():
                if source == PRIMARY:
                    cond[pair][coin] = (lo > 0, own[pair[0]][0] > 0, own[pair[0]][0])
                else:
                    cross[pair].append(f"{source} {coin.upper()} {mean:+,.0f}")
            if source != PRIMARY:
                continue
            refs = {
                "fees only": Costs("fee_only", FEE_BPS),
                "EXP-013 assumption 0.01%/h": PERPS,
            }
            for label, costs in refs.items():
                rng = np.random.default_rng(SEED)
                print(
                    f"\n--- {coin.upper()} same window, reference costs: {label} (context only) ---"
                )
                ref = {n[:2]: simulate(df, t, costs).iloc[a:b][keep] for n, t in targets.items()}
                names = {n[:2]: n for n in targets}
                table([(names[k], r, None) for k, r in ref.items()], up, rng)
                pairs(ref, rng)

    print("\n=== Decision (Deribit funding; pass = both conditions on >= 2 of 3 coins) ===")
    passed: list[tuple[float, tuple[str, str]]] = []
    for pair, by_coin in cond.items():
        adds = sum(1 for c in by_coin.values() if c[0])
        positive = sum(1 for c in by_coin.values() if c[1])
        both = sum(1 for c in by_coin.values() if c[0] and c[1])
        verdict = "PASS" if both >= 2 else "not shown"
        if both >= 2:
            passed.append((sum(c[2] for c in by_coin.values()), pair))
        print(
            f"  {pair[0]} vs {pair[1]}: short side adds on {adds}/{len(by_coin)} coins; "
            f"{pair[0]} itself above $0 on {positive}/{len(by_coin)}; both on {both} -> {verdict}"
        )
        print(f"    cross-checks (L+S minus L, $/yr): {'; '.join(cross[pair])}")
    if passed:
        print(f"paper candidate: {max(passed)[1][0]}")
    else:
        print("no rule passes: the short side is not shown to add money at real funding")


if __name__ == "__main__":
    main()
