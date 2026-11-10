"""EXP-2026-010 holdout: the two ideas chosen from the folds, evaluated once on the sealed
last 180 days. Do not add ideas here after seeing these numbers."""

from trader.research.lab import PERPS, SPOT, evaluate, load_csv, sma_stance, squeeze_breakout

DATA = {m: load_csv(f"data/raw/{m.lower()}_usd_4h.csv") for m in ("SOL", "BTC", "ETH")}
CHOSEN = {
    "squeeze 42 q0.25 stop3.0 L": squeeze_breakout(42, 0.25, 3.0, False),
    "sma_stance 50/200 L": sma_stance(50, 200, False),
}
print("Sealed holdout: last 180 days. 1x after costs.")
for costs in (SPOT, PERPS):
    for name, sig in CHOSEN.items():
        line = []
        for m, df in DATA.items():
            (r,) = evaluate(df, sig, costs, holdout=True)
            line.append(
                f"{m} {r.total_return * 100:+.1f}% (B&H {r.buy_hold * 100:+.1f}%, dd {r.max_drawdown * 100:.0f}%, n={r.trades})"
            )
        print(f"{costs.name:<14}{name:<28}" + " | ".join(line))
