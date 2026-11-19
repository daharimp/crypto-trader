"""EXP-2026-010: research sweep of baseline ideas on real 4h candles (research only).

Run: uv run python research/run_sweep.py > research/EXP-2026-010-results.txt
The sealed holdout (last 180 days) is NOT touched here.
"""

from __future__ import annotations

from statistics import mean

from trader.research.lab import (
    PERPS,
    SPOT,
    donchian,
    evaluate,
    load_csv,
    rsi_reversion,
    sma_stance,
    squeeze_breakout,
    tsmom,
    with_trend_filter,
)

DATA = {m: load_csv(f"data/raw/{m.lower()}_usd_4h.csv") for m in ("SOL", "BTC", "ETH")}
IDEAS = {}
for sh in (True, False):
    tag = "LS" if sh else "L"
    IDEAS[f"sma_stance 20/50 {tag}"] = sma_stance(20, 50, sh)
    IDEAS[f"sma_stance 50/200 {tag}"] = sma_stance(50, 200, sh)
    for lb in (42, 126, 252):
        IDEAS[f"tsmom {lb} {tag}"] = tsmom(lb, sh)
    for e, x in ((20, 10), (55, 20), (120, 40)):
        IDEAS[f"donchian {e}/{x} {tag}"] = donchian(e, x, sh)
        IDEAS[f"donchian {e}/{x} {tag} +trend200"] = with_trend_filter(donchian(e, x, sh), 200)
    for n, q, st in ((20, 0.2, 2.0), (20, 0.3, 3.0), (42, 0.25, 3.0)):
        IDEAS[f"squeeze {n} q{q} stop{st} {tag}"] = squeeze_breakout(n, q, st, sh)
for b, s in ((25, 50), (30, 60)):
    IDEAS[f"rsi_reversion 14 <{b} >{s} trend200 L"] = rsi_reversion(14, b, s, 200)

rows = []
for costs in (PERPS, SPOT):
    for name, sig in IDEAS.items():
        per = {m: evaluate(df, sig, costs) for m, df in DATA.items()}
        flat = [r for rs in per.values() for r in rs]
        beat = sum(r.total_return > r.buy_hold for r in flat)
        positive = sum(r.total_return > 0 for r in flat)
        rows.append(
            (
                costs.name,
                name,
                positive,
                beat,
                mean(r.sortino for r in flat),
                mean(r.total_return for r in flat),
                max(r.max_drawdown for r in flat),
                sum(r.trades for r in flat),
                per,
            )
        )

rows.sort(key=lambda x: (x[2] + x[3], x[4]), reverse=True)
print("9 tests per idea = 3 coins x 3 time periods. 1x, after costs. Holdout sealed.")
print(
    f"{'venue':<14}{'idea':<38}{'>0':>4}{'>B&H':>6}{'sortino':>9}{'avg ret':>9}{'worst DD':>9}{'trades':>7}"
)
for v, n, p, b, so, ar, dd, tr, _ in rows[:25]:
    print(f"{v:<14}{n:<38}{p:>4}{b:>6}{so:>9.2f}{ar * 100:>8.1f}%{dd * 100:>8.1f}%{tr:>7}")
print("\nBuy & hold per period (SOL / BTC / ETH):")
ref = rows[0][8]
for k in range(3):
    print(
        f"  period {k + 1}: "
        + " / ".join(f"{ref[m][k].buy_hold * 100:+.0f}%" for m in ("SOL", "BTC", "ETH"))
    )
print("\nTop 3 per coin detail:")
for v, n, *_, per in rows[:3]:
    print(f"\n{v} | {n}")
    for m, rs in per.items():
        print(
            f"  {m}: "
            + " | ".join(
                f"{r.total_return * 100:+.0f}% vs B&H {r.buy_hold * 100:+.0f}% dd {r.max_drawdown * 100:.0f}% n={r.trades}"
                for r in rs
            )
        )
