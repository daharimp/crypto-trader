"""The real bot loop with a size range, against the research replay (ADR-054).

Drives ``PerpsSession`` (the code the server runs) hour by hour over stored candles for the
ten-coin hourly account with a 0.5% to 1.5% range, feeding it the way the exchange does (719
completed candles and the forming one, for 1h, 4h and 1d), and compares its events, sizes
and scores with the research replay of the composite's wide-range account (EXP-2026-026) on
the same window. The range lives only in memory here; no settings file is read or written
for it.

Usage: python research/live_path_range.py <data_dir> <cache_dir> [days] [configs_dir]
"""

from __future__ import annotations

import bisect
import csv
import dataclasses
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp024_lib as lib
import exp026_lib as x

from trader.perps.candles import PacedFetcher
from trader.perps.params import PerpsParams, load_perps_params
from trader.perps.session import PerpsSession
from trader.perps.signals import DEFAULT_SIGNAL, make_signal

D = Decimal
END = datetime(2026, 11, 24, tzinfo=UTC)
LOW, HIGH = D("0.5"), D("1.5")
STEP = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}
DAY_MS, HOUR_MS = 86_400_000, 3_600_000
KINDS = {"OPENED", "CLOSED", "TAKE_PROFIT", "LIQUIDATED", "OPEN_REJECTED", "DAY_HALTED"}
MONEY = ("entry", "exit", "size_usd", "collateral_usd", "pnl_usd", "fees_usd", "fee_usd")
Rows = list[list[float]]


def load_series(data: Path, coins: list[str]) -> dict[tuple[str, str], Rows]:
    """Stored 1h and 4h candles a coin, and UTC days built from the 4h candles."""
    series: dict[tuple[str, str], Rows] = {}
    for c in coins:
        for tf in ("1h", "4h"):
            with (data / f"{c.lower()}_{tf}.csv").open() as f:
                series[c, tf] = [
                    [
                        datetime.fromisoformat(r["ts_utc"].replace("Z", "+00:00")).timestamp()
                        * 1000,
                        *(float(r[k]) for k in ("open", "high", "low", "close", "volume")),
                    ]
                    for r in csv.DictReader(f)
                ]
        days: dict[float, Rows] = {}
        for r in series[c, "4h"]:
            days.setdefault(r[0] - r[0] % DAY_MS, []).append(r)
        # Reason: a daily candle's close is the close of its last 4h candle.
        series[c, "1d"] = [
            [d, rows[0][1], max(r[2] for r in rows), min(r[3] for r in rows), rows[-1][4], 0.0]
            for d, rows in sorted(days.items())
        ]
    return series


class Exchange:
    """A feed answering as of ``now``: up to 719 completed candles and the forming one."""

    def __init__(self, series: dict[tuple[str, str], Rows]) -> None:
        self.series, self.now, self.calls = series, END, 0
        self.opens = {k: [r[0] for r in rows] for k, rows in series.items()}

    def __call__(self, symbol: str, tf: str) -> Rows:
        self.calls += 1
        c = symbol.split("/")[0]
        now_ms = int(self.now.timestamp() * 1000)
        step_ms = int(STEP[tf].total_seconds() * 1000)
        i = bisect.bisect_right(self.opens[c, tf], now_ms - step_ms)
        done = self.series[c, tf][max(0, i - 719) : i]
        # Reason: the forming candle's latest price is the open of the hour that contains
        # ``now``, which is where the replay fills a decision.
        hour = now_ms - now_ms % HOUR_MS
        j = bisect.bisect_left(self.opens[c, "1h"], hour)
        known = j < len(self.opens[c, "1h"]) and self.opens[c, "1h"][j] == hour
        px = self.series[c, "1h"][j][1] if known else done[-1][4]
        return [*done, [float(now_ms - now_ms % step_ms), px, px, px, px, 0.0]]


def drive(params: PerpsParams, feed: Exchange, start: datetime) -> list[dict[str, Any]]:
    """Run the session once an hour, four minutes past, from ``start`` to ``END``."""
    tmp = Path(tempfile.mkdtemp())
    session = PerpsSession(
        params,
        PacedFetcher(feed, spacing_s=0.0),
        tmp / "state.json",
        tmp / "events.jsonl",
        signal=make_signal(DEFAULT_SIGNAL, 6),
        signal_name=DEFAULT_SIGNAL,
        timeframe="1h",
        trend_timeframe="4h",
        settle_seconds=180,
    )
    events: list[dict[str, Any]] = []
    now = start + timedelta(hours=1, minutes=4)
    while now < END + timedelta(minutes=5):
        feed.now = now
        assert session.due(now), now
        events += session.cycle(now)
        now += timedelta(hours=1)
    print(
        f"live path: {session.meta['cycles']} hourly cycles, "
        f"{feed.calls // session.meta['cycles']} candle requests a cycle"
    )
    return events


def key(e: dict[str, Any]) -> tuple[Any, ...]:
    """An event's identity: the hour it belongs to, what happened, and to which market."""
    hour = datetime.fromisoformat(e["at_utc"]).replace(minute=0, second=0, microsecond=0)
    return (hour.isoformat(), e["event"], e.get("market"), e.get("side"), e.get("reason"))


def main() -> None:
    """Run both and print how they differ."""
    data, cache = Path(sys.argv[1]), Path(sys.argv[2])
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    configs = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("configs")
    start = END - timedelta(days=days)
    flat = load_perps_params(configs, "top10.yaml")
    ranged = dataclasses.replace(
        flat, min_collateral_per_position_pct=LOW, max_collateral_per_position_pct=HIGH
    )
    coins = list(flat.markets)
    live = [e for e in drive(ranged, Exchange(load_series(data, coins)), start)]
    live = [e for e in live if e["event"] in KINDS]

    feed = lib.build_feed(data, "1h", coins, cache)
    scorer = x.Scorer(feed, tuple(coins), feed.signals(), x.features(feed, cache))

    def sizer(scores: x.Scores) -> Decimal:
        return (LOW + (HIGH - LOW) * scores["MC"]).quantize(D("0.0001"))

    result, entries = x.run(flat, feed, start, END, coins=coins, scorer=scorer, sizer=sizer)
    replay = [
        e for e in result.events if e["event"] in KINDS and e.get("reason") != "END_OF_REPLAY"
    ]
    same = sorted(map(key, live)) == sorted(map(key, replay))
    print(f"events: live path {len(live)}, replay {len(replay)}; same sequence: {same}")
    by_key = {key(e): e for e in replay}
    gaps: dict[str, list[Decimal]] = {}
    for e in live:
        other = by_key.get(key(e), {})
        for f in MONEY:
            if f in e and f in other:
                gaps.setdefault(f, []).append(abs(D(e[f]) - D(other[f])))
    for f, rows in gaps.items():
        print(
            f"  {f}: {len(rows)} compared, largest difference ${max(rows):.4f}, "
            f"{sum(1 for g in rows if g == 0)} equal"
        )
    research = {(en.market, en.at_utc[:13]): en for en in entries}
    score_gap, sizes = D(0), []
    for e in (e for e in live if e["event"] == "OPENED"):
        en = research[e["market"], key(e)[0][:13]]
        score_gap = max(score_gap, abs(D(e["confidence"]) - en.scores["MC"]))
        sizes.append(D(e["collateral_pct"]))
    print(
        f"scores: {len(sizes)} opens, largest difference {score_gap:.4f}; sizes used "
        f"{min(sizes):.2f}% to {max(sizes):.2f}% of equity, mean {sum(sizes) / len(sizes):.2f}%"
    )


if __name__ == "__main__":
    main()
