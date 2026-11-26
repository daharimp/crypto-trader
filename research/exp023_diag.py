"""EXP-2026-023 diagnosis numbers: how alike the coins are, and how routine the live loss is.

Three questions about the live settings, answered by the replay harness:
1. how often do the BTC, ETH and SOL signals all point the same way;
2. how correlated are the three coins' daily returns;
3. for ``main`` and ``spot-perps``: how often does the account lose 7% in a day or 9% in
   two or seven days, and on how many days a year do two or all three coins stop out.

Usage: python research/exp023_diag.py <data_dir> <cache_dir>
"""

from __future__ import annotations

import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import exp023_lib as lib

from trader.perps.math import PerpSide


def agreement(feed: lib.Feed) -> dict[str, float]:
    """Share of 4h bars from 2021-01 on where all three signals are on one side."""
    sig = feed.signals()
    first = next(i for i, t in enumerate(feed.times) if t >= datetime(2021, 1, 1, tzinfo=UTC))
    seen: Counter[str] = Counter()
    for j in range(first, len(feed.times)):
        sides = [sig[m][j] for m in lib.COINS]
        longs = sum(s == PerpSide.LONG for s in sides)
        shorts = sum(s == PerpSide.SHORT for s in sides)
        seen["all same side" if max(longs, shorts) == len(lib.COINS) else "split"] += 1
    total = sum(seen.values())
    return {k: round(v / total * 100, 1) for k, v in seen.items()}


def daily_closes(feed: lib.Feed, market: str) -> dict[date, float]:
    """The close of the last 4h candle of each UTC day."""
    return {t.date(): float(feed.rows[market][t][4]) for t in feed.times if t.hour == 20}


def corr(x: list[float], y: list[float]) -> float:
    """Pearson correlation."""
    mx, my = statistics.mean(x), statistics.mean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    return cov / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))


def coin_correlations(feed: lib.Feed) -> None:
    """Print the daily-return correlation of each pair of coins in two periods."""
    closes = {m: daily_closes(feed, m) for m in lib.COINS}
    days = sorted(set.intersection(*(set(d) for d in closes.values())))
    for first, last in ((2021, 2023), (2024, 2026)):
        span = [d for d in days if first <= d.year <= last]
        rets = {
            m: [closes[m][b] / closes[m][a] - 1 for a, b in zip(span, span[1:], strict=False)]
            for m in lib.COINS
        }
        pairs = (("BTC", "ETH"), ("BTC", "SOL"), ("ETH", "SOL"))
        got = {f"{p}-{q}": round(corr(rets[p], rets[q]), 2) for p, q in pairs}
        print(f"daily-return correlation {first}-{last}: {got}")


def loss_routine(feed: lib.Feed, name: str, window: str) -> None:
    """Print how often one account, as configured, has a loss like the live one."""
    params, _ = lib.account(name)
    start, end = lib.WINDOWS[window]
    out = lib.run(params, feed, start, end)
    eq = [v for _, v in sorted(out.daily_equity.items())]
    one = [b / a - 1 for a, b in zip(eq, eq[1:], strict=False)]
    two = [eq[i + 2] / eq[i] - 1 for i in range(len(eq) - 2)]
    week = [eq[i + 7] / eq[i] - 1 for i in range(len(eq) - 7)]
    stops: defaultdict[str, set[str]] = defaultdict(set)
    for e in out.events:
        if e["event"] == "CLOSED" and e["reason"] == "STOP_LOSS":
            stops[e["at_utc"][:10]].add(e["market"])
    years = (end - start).days / 365.25
    triple = sum(1 for v in stops.values() if len(v) == 3)
    double = sum(1 for v in stops.values() if len(v) == 2)
    print(
        f"{name:10} {window:4}: days <= -7%: {sum(x <= -0.07 for x in one) / years:.1f} a year; "
        f"2-day <= -9%: {sum(x <= -0.09 for x in two) / len(two) * 100:.1f}% of spans; "
        f"7-day <= -9%: {sum(x <= -0.09 for x in week) / len(week) * 100:.1f}% of spans; "
        f"losing 7-day spans {sum(x < 0 for x in week) / len(week) * 100:.0f}%; "
        f"days with all 3 coins stopped: {triple / years:.1f} a year, 2 coins: "
        f"{double / years:.1f} a year; days with any stop {len(stops) / years:.0f} a year"
    )


def main() -> None:
    """Print the three diagnosis blocks."""
    feed = lib.build_feed(Path(sys.argv[1]), "4h", Path(sys.argv[2]))
    print("== EXP-2026-023 diagnosis (live settings, 4h bars)")
    print(f"signal agreement across BTC, ETH, SOL (2021-01 on, % of 4h bars): {agreement(feed)}")
    coin_correlations(feed)
    for name in ("main", "spot-perps"):
        for window in ("dev", "hold"):
            loss_routine(feed, name, window)


if __name__ == "__main__":
    main()
