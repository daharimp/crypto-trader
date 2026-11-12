"""EXP-2026-013: two-sided vs long-only trend following (plan: research/EXP-2026-013-plan.md).

Research only. Prints every pre-registered trial for every coin, at primary (approved perps)
costs and at the optimistic no-borrow bound. Dollars are on a constant $2,500.

Usage: uv run python research/run_exp013.py   (needs data/long/{btc,eth,sol}_usd_4h.csv)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trader.research.lab import (
    BARS_PER_YEAR,
    PERPS,
    Costs,
    Signal,
    load_csv,
    simulate,
    tsmom,
    vol_target,
)

CAPITAL = 2500.0
MONTH = 180  # 30 days of 4h bars
WARMUP = 12 * MONTH + 15  # 12-month lookback plus a little slack
VOL_LOOKBACK = 360  # 60 days, close to the ~60-day centre of mass in Moskowitz et al. (2012)
BLOCK, RESAMPLES = MONTH, 2000
COSTS = {"primary": PERPS, "no-borrow bound": Costs("perps_fee_only", PERPS.fee_bps_per_side)}


def blend(shorts: bool) -> Signal:
    """Equal-weight 1/3/12-month TSMOM (Hurst, Ooi & Pedersen 2017)."""
    parts = [tsmom(m * MONTH, shorts) for m in (1, 3, 12)]

    def f(df: pd.DataFrame) -> pd.Series:
        return sum((p(df) for p in parts[1:]), parts[0](df)) / 3

    return f


TRIALS: dict[str, Signal] = {
    "T1 blend  L+S  full": blend(True),
    "T2 blend  L    full": blend(False),
    "T3 blend  L+S  vol40": vol_target(blend(True), 0.4, VOL_LOOKBACK),
    "T4 blend  L    vol40": vol_target(blend(False), 0.4, VOL_LOOKBACK),
    "T5 1-mo   L+S  full": tsmom(MONTH, True),
    "T6 1-mo   L    full": tsmom(MONTH, False),
    "T7 1-mo   L+S  vol40": vol_target(tsmom(MONTH, True), 0.4, VOL_LOOKBACK),
    "T8 1-mo   L    vol40": vol_target(tsmom(MONTH, False), 0.4, VOL_LOOKBACK),
}
PAIRS = [("T1", "T2"), ("T3", "T4"), ("T5", "T6"), ("T7", "T8")]


def per_year(r: pd.Series) -> pd.Series:
    """Dollar result of each calendar year on $2,500."""
    return CAPITAL * ((1 + r).groupby(r.index.year).prod() - 1)


def boot(r: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """90% range of dollars per year by circular block bootstrap of per-bar returns."""
    n = len(r)
    k = int(np.ceil(n / BLOCK))
    starts = rng.integers(0, n, size=(RESAMPLES, k))
    idx = (starts[:, :, None] + np.arange(BLOCK)[None, None, :]).reshape(RESAMPLES, -1)[:, :n] % n
    means = r[idx].mean(axis=1) * BARS_PER_YEAR * CAPITAL
    lo, hi = np.percentile(means, [5, 95])
    return float(lo), float(hi)


def main() -> None:
    """Print one block per coin and cost set, then the decision."""
    passes = {p: 0 for p in PAIRS}
    for coin in ("btc", "eth", "sol"):
        df = load_csv(f"data/long/{coin}_usd_4h.csv")
        span = f"{df.index[WARMUP].date()} to {df.index[-1].date()}"
        bh = df["open"].shift(-1) / df["open"] - 1
        bh = bh.iloc[WARMUP:].fillna(0.0)
        up_years = per_year(bh) > 0
        for cname, costs in COSTS.items():
            rng = np.random.default_rng(13)
            print(f"\n=== {coin.upper()} {span}, {cname} costs, $2,500 constant ===")
            print(
                f"{'trial':<22}{'$/yr':>8}{'90% range':>18}{'worst yr':>10}{'up yrs':>9}{'down yrs':>10}{'max DD':>8}"
            )
            rets: dict[str, pd.Series] = {}
            rows = [("BH buy and hold", bh)]
            for name, sig in TRIALS.items():
                r = simulate(df, sig(df), costs).iloc[WARMUP:]
                rets[name[:2]] = r
                rows.append((name, r))
            for name, r in rows:
                yrs = per_year(r)
                eq = (1 + r).cumprod()
                lo, hi = boot(r.to_numpy(), rng)
                print(
                    f"{name:<22}{r.mean() * BARS_PER_YEAR * CAPITAL:>8,.0f}{f'{lo:,.0f} to {hi:,.0f}':>18}"
                    f"{yrs.min():>10,.0f}{yrs[up_years].mean():>9,.0f}{yrs[~up_years].mean():>10,.0f}"
                    f"{(1 - eq / eq.cummax()).max() * 100:>7.0f}%"
                )
            print("short side added (L+S minus L), $/yr with 90% range:")
            for a, b in PAIRS:
                d = (rets[a] - rets[b]).to_numpy()
                lo, hi = boot(d, rng)
                ok = lo > 0
                if cname == "primary" and ok:
                    passes[(a, b)] += 1
                print(
                    f"  {a} vs {b}: {d.mean() * BARS_PER_YEAR * CAPITAL:>7,.0f}  ({lo:,.0f} to {hi:,.0f}){'  ADDS' if ok else ''}"
                )
    print("\n=== Decision (primary costs; pass = 90% range above $0 on >= 2 of 3 coins) ===")
    for (a, b), n in passes.items():
        print(
            f"  {a} vs {b}: range above $0 on {n}/3 coins -> {'short side adds money' if n >= 2 else 'not shown'}"
        )


if __name__ == "__main__":
    main()
