"""EXP-2026-011: ten hypotheses from the 2026-11-10 research pass (research only).

Folds only: the 180-day holdout was opened in EXP-2026-010 and is no longer a clean test;
the next clean test is forward paper trading. Every variant tried is printed (11 rows incl.
the control), so the number of trials is on the record.
"""

from __future__ import annotations

from statistics import mean

from trader.research.lab import (
    PERPS,
    SPOT,
    donchian_ensemble,
    evaluate,
    load_csv,
    squeeze_plus,
    tsmom,
    vol_target,
)

DATA = {m: load_csv(f"data/raw/{m.lower()}_usd_4h.csv") for m in ("SOL", "BTC", "ETH")}
H = {
    "H0  control: squeeze 42 L": squeeze_plus(),
    "H1  + volume >1.5x avg": squeeze_plus(vol_mult=1.5),
    "H2  + uptrend only (SMA200)": squeeze_plus(trend=200),
    "H3  + time stop 12 bars": squeeze_plus(time_stop=12),
    "H4  + shorts below SMA200": squeeze_plus(trend=200, shorts_below_trend=True),
    "H5  + vol-target 40%": vol_target(squeeze_plus(), 0.4),
    "H6  Donchian ensemble L": donchian_ensemble(),
    "H7  Donchian ensemble L + vol-target": vol_target(donchian_ensemble(), 0.4),
    "H8  slow momentum 12wk L": tsmom(504, False),
    "H9  slow momentum 12wk L + vol-target": vol_target(tsmom(504, False), 0.4),
    "H10 squeeze + volume + trend + vol-target": vol_target(
        squeeze_plus(vol_mult=1.5, trend=200), 0.4
    ),
}
for costs in (SPOT, PERPS):
    print(f"\n=== {costs.name}: 9 tests per idea (3 coins x 3 periods), after costs ===")
    print(
        f"{'idea':<44}{'>0':>4}{'>B&H':>6}{'sortino':>9}{'avg ret':>9}{'worst DD':>9}{'avg exp':>8}{'trades':>7}"
    )
    for name, sig in H.items():
        flat = [r for df in DATA.values() for r in evaluate(df, sig, costs)]
        print(
            f"{name:<44}{sum(r.total_return > 0 for r in flat):>4}{sum(r.total_return > r.buy_hold for r in flat):>6}"
            f"{mean(r.sortino for r in flat):>9.2f}{mean(r.total_return for r in flat) * 100:>8.1f}%"
            f"{max(r.max_drawdown for r in flat) * 100:>8.1f}%{mean(r.exposure for r in flat) * 100:>7.0f}%"
            f"{sum(r.trades for r in flat):>7}"
        )
