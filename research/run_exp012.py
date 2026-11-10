"""EXP-2026-012: retail bot styles (Pionex grid, Cryptohopper DCA) vs our squeeze breakout.

Research only (ADR-028). Folds only: the 180-day holdout was opened in EXP-2026-010. Every
variant tried is printed, so the number of trials is on the record. Same three folds and
coins as EXP-2026-011; bots run on hourly candles inside each fold's dates. All figures are
in dollars from a $2,500 start per test.

Usage: uv run python research/run_exp012.py   (needs data/raw/{sol,btc,eth}_usd_{1h,4h}.csv)
"""

from __future__ import annotations

from collections.abc import Callable
from statistics import mean

import pandas as pd

from trader.research.bots import KRAKEN, PIONEX, BotCosts, BotResult, dca_bot, grid_bot, plain_dca
from trader.research.lab import Costs, load_csv, metrics, split, squeeze_plus

CAPITAL = 2500.0
COINS = ("SOL", "BTC", "ETH")
H4 = {m: load_csv(f"data/raw/{m.lower()}_usd_4h.csv") for m in COINS}
H1 = {m: load_csv(f"data/raw/{m.lower()}_usd_1h.csv") for m in COINS}

Bot = Callable[[pd.DataFrame, float, BotCosts], BotResult]
BOTS: dict[str, Bot] = {
    "G1 grid fixed +-25%, 20 lines": lambda d, c, k: grid_bot(d, c, k, 0.25, 20),
    "G2 grid rebuilt monthly +-15%": lambda d, c, k: grid_bot(d, c, k, 0.15, 20, 720),
    "G3 grid rebuilt weekly +-8%": lambda d, c, k: grid_bot(d, c, k, 0.08, 20, 168),
    "D1 DCA bot 5x2% steps, TP 1.5%": lambda d, c, k: dca_bot(d, c, k, 5, 0.02, 1.5, 0.015),
    "D2 DCA bot 5x4% steps, TP 3%": lambda d, c, k: dca_bot(d, c, k, 5, 0.04, 1.5, 0.03),
    "B1 plain weekly DCA": lambda d, c, k: plain_dca(d, c, k),
}
SIGNALS = {
    "S0 squeeze breakout (control)": squeeze_plus(),
    "S1 squeeze, tighter stop 2 ATR": squeeze_plus(stop_atr=2.0),
    "S2 squeeze, looser stop 4 ATR": squeeze_plus(stop_atr=4.0),
}
# Reason: the lab charges one blended rate per side; use each venue's taker rate.
LAB_COSTS = {
    "kraken": Costs("kraken_spot", KRAKEN.taker_bps),
    "pionex": Costs("pionex_spot", PIONEX.taker_bps),
}


def windows() -> list[tuple[str, pd.Timestamp, pd.Timestamp, tuple[int, int]]]:
    """(coin, start, end, 4h bar range) for each research fold."""
    out = []
    for m, df in H4.items():
        folds, _ = split(df)
        out += [(m, df.index[a], df.index[b], (a, b)) for a, b in folds]
    return out


def row(
    name: str, ends: list[float], bh: list[float], dds: list[float], fees: str, fills: int
) -> str:
    """One table line."""
    return (
        f"{name:<34}{sum(e > CAPITAL for e in ends):>4}{sum(e > b for e, b in zip(ends, bh, strict=True)):>6}"
        f"{mean(ends):>10,.0f}{min(ends):>10,.0f}{max(dds) * 100:>8.0f}%{fees:>9}{fills:>7}"
    )


def main() -> None:
    """Print one table per cost set."""
    wins = windows()
    print(f"folds: {[(m, s.date().isoformat(), e.date().isoformat()) for m, s, e, _ in wins]}")
    for venue, bot_costs in (("kraken", KRAKEN), ("pionex", PIONEX)):
        print(f"\n=== {venue} fees: 9 tests (3 coins x 3 periods), $2,500 start each ===")
        print(
            f"{'idea':<34}{'>$0':>4}{'>B&H':>6}{'avg end':>10}{'worst end':>10}{'worst DD':>9}{'avg fee':>9}{'fills':>7}"
        )
        bh_ends: list[float] = []
        bh_dds: list[float] = []
        for m, s, e, _ in wins:
            c = H1[m].loc[s : e - pd.Timedelta(hours=1), "close"]
            bh_ends.append(CAPITAL * float(c.iloc[-1] / H1[m].loc[s, "open"]))
            bh_dds.append(float((1 - c / c.cummax()).max()))
        print(row("BH buy and hold (reference)", bh_ends, bh_ends, bh_dds, "-", 0))
        for name, bot in BOTS.items():
            rs = [
                bot(H1[m].loc[s : e - pd.Timedelta(hours=1)], CAPITAL, bot_costs)
                for m, s, e, _ in wins
            ]
            print(
                row(
                    name,
                    [r.end for r in rs],
                    [r.buy_hold_end for r in rs],
                    [r.max_drawdown for r in rs],
                    f"{mean(r.fees for r in rs):,.0f}",
                    sum(r.fills for r in rs),
                )
            )
        for name, sig in SIGNALS.items():
            ends, bhs, dds, trades = [], [], [], 0
            for m, _, _, (a, b) in wins:
                df = H4[m]
                res = metrics(df.iloc[a:b], sig(df).iloc[a:b], LAB_COSTS[venue])
                ends.append(CAPITAL * (1 + res.total_return))
                bhs.append(CAPITAL * (1 + res.buy_hold))
                dds.append(res.max_drawdown)
                trades += res.trades
            print(row(name, ends, bhs, dds, "-", trades))


if __name__ == "__main__":
    main()
