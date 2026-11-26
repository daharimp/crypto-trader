"""EXP-2026-024 replay harness: the paper perps engine on any list of coins (research only).

``exp023_lib`` replays the three live coins. This module does the same for any universe:
coins may be listed at different times, miss bars, or stop trading, so the clock is the
union of every coin's bars and each coin takes part only while it has data.

Per bar *t* (timestamps are the bar's close time, as in ``trader.perps.session.cycle``):
1. mark: accrue borrow, check stops, liquidations and take-profits on the bar's extremes
   for every position whose coin has this bar (a coin without the bar is carried at its
   last close and cannot stop out on it), then roll the UTC day;
2. decide from closes up to *t* for every coin that has bar *t* and bar *t+1*;
3. fill at the open of bar *t+1*.
A position in a coin whose data has ended is closed at its last close ("DATA_ENDED").

Signals and typical daily moves are cached per coin, stamped with the candle file's row
count and last timestamp so a changed file rebuilds its cache.

``group_cap`` is the same-side open-risk cap of ``exp023_lib``: the summed loss-at-stop of
open positions on one side may not pass this % of equity; coins opening together on a bar
share the remaining room equally.
"""

from __future__ import annotations

import bisect
import dataclasses
import pickle
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as base

from trader.perps.math import PerpSide, typical_daily_move
from trader.perps.params import PerpsParams
from trader.perps.simulator import PaperPerpsAccount

Row = base.Row
STEP = base.STEP
Series = dict[datetime, Any]


@dataclass
class Feed:
    """Candles of one execution timeframe for a set of coins, with per-coin caches."""

    tf: str
    coins: tuple[str, ...]
    times: list[datetime]
    rows: dict[str, dict[datetime, Row]]
    order: dict[str, list[datetime]]  # each coin's own bar times, ascending
    trend: dict[str, list[Row]] | None  # 4h candles when the execution timeframe is 1h
    cache_dir: Path | None = None
    _mem: dict[tuple[str, str], Series] = field(default_factory=dict)

    def views(self, m: str) -> list[tuple[datetime, list[Decimal], list[Decimal]]]:
        """Per bar of coin ``m``: (time, closes the signal sees, closes for the daily move)."""
        out: list[tuple[datetime, list[Decimal], list[Decimal]]] = []
        if self.trend is None:
            hist: list[Decimal] = []
            for t in self.order[m]:
                hist.append(self.rows[m][t][4])
                view = hist[-base.KEEP :]
                out.append((t, view, view))
            return out
        candles = self.trend[m]
        opens = [r[0] for r in candles]
        for t in self.order[m]:
            decided = t + STEP[self.tf]
            # Reason: session._trend_view uses candles with open + 4h <= the decision time.
            i = bisect.bisect_right(opens, decided - base.TREND_STEP) - 1
            done = [r[4] for r in candles[max(0, i - base.KEEP + 1) : i + 1]] if i >= 0 else []
            at_boundary = bool(done) and candles[i][0] + base.TREND_STEP == decided
            closes = done if at_boundary else [*done, self.rows[m][t][4]]
            out.append((t, closes, done))
        return out

    def _stamp(self, m: str) -> tuple[int, datetime, int, datetime | None]:
        trend = self.trend[m] if self.trend is not None else []
        return (
            len(self.order[m]),
            self.order[m][-1],
            len(trend),
            trend[-1][0] if trend else None,
        )

    def _series(self, name: str, m: str, build: Callable[[], Series]) -> Series:
        key = (name, m)
        if key in self._mem:
            return self._mem[key]
        path = self.cache_dir / f"{self.tf}-{name}-{m.lower()}.pkl" if self.cache_dir else None
        value: Series | None = None
        if path is not None and path.exists():
            with open(path, "rb") as f:
                stamp, cached = pickle.load(f)  # noqa: S301 - our own cache file
            if stamp == self._stamp(m):
                value = cached
        if value is None:
            value = build()
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{id(self)}.tmp")
                with open(tmp, "wb") as f:
                    pickle.dump((self._stamp(m), value), f)
                tmp.replace(path)
        self._mem[key] = value
        return value

    def signal(self, m: str, label: str, factory: Callable[[], base.SignalFn]) -> Series:
        """Signal of one coin per bar time (cached under ``label``)."""

        def build() -> Series:
            fn = factory()
            return {t: fn(closes) for t, closes, _ in self.views(m)}

        return self._series(f"sig-{label}", m, build)

    def signals(
        self, label: str = "live", factory: Callable[[], base.SignalFn] = base.live_signal
    ) -> dict[str, Series]:
        """Signal per coin per bar time. Use a new label for every different signal."""
        return {m: self.signal(m, label, factory) for m in self.coins}

    def move(self, m: str) -> Series:
        """Typical daily move (ADR-032) of one coin per bar time."""

        def build() -> Series:
            return {t: typical_daily_move(mc[-200:], 6) for t, _, mc in self.views(m)}

        return self._series("moves", m, build)

    def moves(self) -> dict[str, Series]:
        """Typical daily move per coin per bar time."""
        return {m: self.move(m) for m in self.coins}


def build_feed(
    data: Path, tf: str, coins: tuple[str, ...] | list[str], cache_dir: Path | None = None
) -> Feed:
    """Load the coins' candles for an execution timeframe."""
    coins = tuple(coins)
    bars = {m: base.load(data, m, tf) for m in coins}
    rows = {m: {r[0]: r for r in bars[m]} for m in coins}
    order = {m: [r[0] for r in bars[m]] for m in coins}
    times = sorted(set().union(*(set(d) for d in rows.values())))
    trend = None if tf == "4h" else {m: base.load(data, m, "4h") for m in coins}
    return Feed(tf, coins, times, rows, order, trend, cache_dir)


def _open_risk_pct(acct: PaperPerpsAccount, side: PerpSide, equity: Decimal) -> Decimal:
    """Summed loss-at-stop of the open positions on ``side``, % of equity."""
    share = acct.params.stop_loss_pct_of_collateral or Decimal(100)
    total = Decimal(0)
    for p in acct.positions.values():
        # Reason: once a take-profit moved the stop to breakeven or better, nothing is at risk.
        if p.side == side and p.moved_stop is None:
            total += p.collateral_usd * share / 100
    return total / equity * 100 if equity > 0 else Decimal(0)


def run(
    params: PerpsParams,
    feed: Feed,
    start: datetime,
    end: datetime,
    *,
    coins: tuple[str, ...] | list[str] | None = None,
    signals: dict[str, Series] | None = None,
    group_cap: Decimal | None = None,
    min_collateral_pct: Decimal = Decimal("0.5"),
) -> base.Result:
    """
    Replay one account over ``[start, end)`` on ``coins`` (default: every coin of the feed).

    Args:
        params (PerpsParams): Account settings; ``markets`` is replaced by ``coins``.
        feed (Feed): Candles and caches.
        start (datetime): First bar.
        end (datetime): Bars opening at or after this are not used.
        coins: Coins traded, in the order the account walks them.
        signals: Output of ``feed.signals(...)``; the live signal when omitted.
        group_cap (Decimal | None): Same-side open-risk cap, % of equity.
        min_collateral_pct (Decimal): Under the cap, an entry whose share of the room is
            smaller than this % of equity is skipped (it is retried on later bars).

    Returns:
        base.Result: Stats, events and daily equity.
    """
    coins = tuple(coins or feed.coins)
    params = dataclasses.replace(params, markets={m: m for m in coins})
    sig = signals if signals is not None else feed.signals()
    mov = feed.moves()
    step = STEP[feed.tf]
    times = feed.times[bisect.bisect_left(feed.times, start) : bisect.bisect_left(feed.times, end)]
    acct = PaperPerpsAccount.start(params, times[0])
    stop_share = (params.stop_loss_pct_of_collateral or Decimal(100)) / 100
    last_time = {m: feed.order[m][-1] for m in coins}
    last_close: dict[str, Decimal] = {}
    daily: dict[date, float] = {}
    peak, max_dd = acct.cash_usd, Decimal(0)
    for n, t in enumerate(times):
        closes_at = t + step
        row = {m: feed.rows[m][t] for m in coins if t in feed.rows[m]}
        for m, r in row.items():
            last_close[m] = r[4]
        for m in [m for m in acct.positions if last_time[m] < t]:
            acct.close(m, last_close, closes_at, reason="DATA_ENDED")
        if n > 0 and acct.positions:
            marks = dict(last_close)
            favorable = {}
            for m, p in acct.positions.items():
                if m in row:
                    long = p.side == PerpSide.LONG
                    marks[m] = row[m][3] if long else row[m][2]
                    favorable[m] = row[m][2] if long else row[m][3]
            acct.mark(
                marks,
                closes_at,
                opens={m: r[1] for m, r in row.items()},
                favorable=favorable,
                closes=dict(last_close),
            )
        elif n > 0:
            acct.mark(dict(last_close), closes_at)
        # Reason: a coin without the next bar keeps its last close as the mark and is skipped.
        px = dict(last_close)
        tradable = []
        for m in row:
            nxt = feed.rows[m].get(closes_at)
            if nxt is not None:
                px[m] = nxt[1]
                tradable.append(m)
        wanted: dict[PerpSide, list[str]] = {PerpSide.LONG: [], PerpSide.SHORT: []}
        for m in tradable:
            move = mov[m].get(t)
            if move is None:
                acct.daily_moves.pop(m, None)
            else:
                acct.daily_moves[m] = move
            target = sig[m].get(t)
            cur = acct.positions.get(m)
            if cur is not None and cur.side != target:
                acct.close(m, px, closes_at, reason="SIGNAL_CHANGED")
            if target is None or m in acct.positions or m in acct.stopped_today:
                continue
            wanted[target].append(m)
        for side, markets in wanted.items():
            for k, m in enumerate(markets):
                if group_cap is not None:
                    equity = acct.equity(px)
                    room = group_cap - _open_risk_pct(acct, side, equity)
                    # Reason: coins opening together share the room equally.
                    pct = min(
                        params.max_collateral_per_position_pct,
                        max(room, Decimal(0)) / (len(markets) - k) / stop_share,
                    )
                    if pct < min_collateral_pct:
                        continue
                    acct.params = dataclasses.replace(params, max_collateral_per_position_pct=pct)
                acct.open(m, side, px, closes_at)
                acct.params = params
        if tradable:
            acct.check_day_loss(px, closes_at)
        equity = acct.equity(px)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
        # Reason: a bar closing at 00:00 belongs to the day that just ended.
        daily[(closes_at - timedelta(seconds=1)).date()] = float(equity)
    final = times[-1] + step
    for m in list(acct.positions):
        acct.close(m, last_close, final, reason="END_OF_REPLAY")
    daily[(final - timedelta(seconds=1)).date()] = float(acct.cash_usd)
    return base.Result(base.summarize(acct, daily, max_dd, start, end), acct.events, daily)


def clusters(events: list[dict[str, Any]]) -> int:
    """Entries counted as decisions: coins opened on the same side within one UTC day are one."""
    return len({(e["at_utc"][:10], e["side"]) for e in events if e["event"] == "OPENED"})


def precompute(data: Path, cache: Path, tf: str, coins: list[str]) -> None:
    """Build the live-signal and daily-move caches for some coins (run several in parallel)."""
    feed = build_feed(data, tf, coins, cache)
    for m in coins:
        feed.signal(m, "live", base.live_signal)
        feed.move(m)
        print(f"cached {tf} {m}", flush=True)


if __name__ == "__main__":
    # python research/exp024_lib.py <data_dir> <cache_dir> <tf> COIN [COIN ...]
    precompute(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4:])
