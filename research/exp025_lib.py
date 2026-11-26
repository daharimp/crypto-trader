"""EXP-2026-025 replay harness: the paper perps engine with three add-ons (research only).

This is the ungrouped loop of ``exp024_lib.run`` (any list of coins, the real
``PaperPerpsAccount``, decisions coin by coin in the account's order) with four switches,
all off by default. With every switch off it reproduces ``exp024_lib.run`` event for event
(``run_exp025.py check``). Plan: ``research/EXP-2026-025-plan.md``.

Per bar *t* (timestamps are the bar's close time): mark, then for every coin that has bar
*t* and bar *t+1*, in order:
1. a position the signal no longer wants is closed ("SIGNAL_CHANGED");
2. **time limit**: a position open T hours or more that has hit no take-profit and is not
   in profit after fees at the fill price is closed ("TIME_LIMIT"); the coin then opens
   nothing on that side until its signal has been flat or on the other side once;
3. a new position opens unless the coin is waiting: the account's own rule (stopped today),
   the **cooldown** (C hours after a trade that lost money after fees), the **stop guard**
   (N opening stops within L days pause the coin P days from the last one) or the time
   limit's block;
4. **correlation sizing**: the new position's collateral is multiplied by a number between
   0.25 and 1 that falls with its 30-day correlation to the positions already open.
Fills are at the open of bar *t+1*.

The add-ons read only the account's own events and completed candles: a trade's result is
summed from its OPENED, TAKE_PROFIT and CLOSED events, and a correlation uses 4h candles
that closed at or before the decision.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import exp023_lib as base
import exp024_lib as lib
import numpy as np

from trader.perps.math import PerpSide, fee_usd, pnl_usd
from trader.perps.params import PerpsParams
from trader.perps.simulator import PaperPerpsAccount, PerpPosition

D = Decimal
CORR_BARS = 180  # 30 days of 4h candles
CORR_MIN_COMMON = 60
ROOT_FLOOR = D("0.25")


@dataclass(frozen=True)
class Addons:
    """Which add-ons are on. The default (all None) is the baseline account."""

    cooldown_hours: int | None = None
    stop_guard: tuple[int, int, int] | None = None  # (N stops, within L days, pause P days)
    corr_sizing: str | None = None  # "tiers" or "root"
    time_limit_hours: int | None = None


@dataclass
class Outcome:
    """One replay: the usual result, how often the add-ons acted, and the size multipliers."""

    result: base.Result
    acts: int
    multipliers: list[float]  # one per opened position, when correlation sizing is on


@dataclass
class Book:
    """What the add-ons remember about each coin, read from the account's own events."""

    addons: Addons
    seen: int = 0
    pnl: dict[str, Decimal] = field(default_factory=dict)  # open trade's result so far
    had_tp: dict[str, bool] = field(default_factory=dict)
    cool_until: dict[str, datetime] = field(default_factory=dict)
    stops: dict[str, list[datetime]] = field(default_factory=dict)
    guard_until: dict[str, datetime] = field(default_factory=dict)
    tl_block: dict[str, PerpSide] = field(default_factory=dict)
    # (add-on, coin, end of the waiting window) for every window that refused an open
    refused: set[tuple[str, str, datetime]] = field(default_factory=set)
    tl_exits: int = 0

    def read(self, acct: PaperPerpsAccount) -> None:
        """Take in the account's new events: trade results, opening stops, waiting windows."""
        for e in acct.events[self.seen :]:
            kind, m = e["event"], e.get("market")
            if kind == "OPENED":
                self.pnl[m], self.had_tp[m] = -D(e["fee_usd"]), False
            elif kind == "TAKE_PROFIT":
                self.pnl[m] += D(e["pnl_usd"]) - D(e["fees_usd"])
                self.had_tp[m] = True
            elif kind == "CLOSED":
                net = self.pnl.pop(m) + D(e["pnl_usd"]) - D(e["fees_usd"])
                first_stop = e["reason"] == "STOP_LOSS" and not self.had_tp[m]
                self._ended(m, datetime.fromisoformat(e["at_utc"]), net, first_stop)
            elif kind == "LIQUIDATED":
                net = self.pnl.pop(m) - D(e["collateral_lost_usd"])
                self._ended(m, datetime.fromisoformat(e["at_utc"]), net, False)
        self.seen = len(acct.events)

    def _ended(self, m: str, at: datetime, net: Decimal, opening_stop: bool) -> None:
        a = self.addons
        if a.cooldown_hours is not None and net < 0:
            self.cool_until[m] = at + timedelta(hours=a.cooldown_hours)
        if a.stop_guard is not None and opening_stop:
            n, look, pause = a.stop_guard
            # Reason: a rolling count; stops older than L days drop out, nothing else resets.
            recent = [x for x in self.stops.get(m, []) if x > at - timedelta(days=look)]
            recent.append(at)
            self.stops[m] = recent
            if len(recent) >= n:
                self.guard_until[m] = at + timedelta(days=pause)

    def signal_seen(self, m: str, target: PerpSide | None) -> None:
        """A flat or opposite signal lifts the time limit's block on that coin."""
        if m in self.tl_block and target != self.tl_block[m]:
            del self.tl_block[m]

    def waiting(self, m: str, target: PerpSide, now: datetime) -> bool:
        """Whether an add-on refuses a new open in ``m`` on side ``target`` at ``now``."""
        hit = False
        for name, table in (("CD", self.cool_until), ("SG", self.guard_until)):
            until = table.get(m)
            if until is not None and now < until:
                self.refused.add((name, m, until))
                hit = True
        return hit or self.tl_block.get(m) == target


class Corr:
    """Correlation of two coins' 4h returns over the last 180 completed 4h candles."""

    def __init__(self, candles: dict[str, list[base.Row]]) -> None:
        """
        Index every coin's 4h returns by the candle's open time.

        Args:
            candles (dict[str, list[base.Row]]): 4h candles per coin, ascending.
        """
        self.ret: dict[str, dict[datetime, float]] = {}
        for m, rows in candles.items():
            # Reason: a return across a gap in the candles is not a 4h return; skip it.
            self.ret[m] = {
                b[0]: float(b[4] / a[4]) - 1
                for a, b in zip(rows, rows[1:], strict=False)
                if b[0] - a[0] == base.TREND_STEP
            }
        self._memo: dict[tuple[str, str, datetime], float] = {}

    def at(self, a: str, b: str, decided_at: datetime) -> float:
        """
        Correlation of ``a`` and ``b`` as known at a decision.

        Args:
            a (str): Coin.
            b (str): Coin.
            decided_at (datetime): Decision time; only candles closed by then are read.

        Returns:
            float: Pearson correlation of the common returns among the last 180 completed
            4h candles; 0 with fewer than 60 in common or no variation.
        """
        # Reason: the newest candle a decision may read opened at least 4h before it, on the
        # 4h grid (00, 04, ... UTC).
        newest = decided_at - base.TREND_STEP
        newest = newest.replace(
            hour=newest.hour - newest.hour % 4, minute=0, second=0, microsecond=0
        )
        key = (min(a, b), max(a, b), newest)
        if key not in self._memo:
            ra, rb = self.ret[a], self.ret[b]
            grid = (newest - k * base.TREND_STEP for k in range(CORR_BARS))
            pairs = [(ra[t], rb[t]) for t in grid if t in ra and t in rb]
            value = 0.0
            if len(pairs) >= CORR_MIN_COMMON:
                x, y = np.array(pairs).T
                if x.std() > 0 and y.std() > 0:
                    value = float(np.corrcoef(x, y)[0, 1])
            self._memo[key] = value
        return self._memo[key]


def four_hour_candles(feed: lib.Feed) -> dict[str, list[base.Row]]:
    """Every coin's 4h candles: the trend candles of an hourly feed, or a 4h feed's own."""
    if feed.trend is not None:
        return feed.trend
    return {m: [feed.rows[m][t] for t in feed.order[m]] for m in feed.coins}


def multiplier(
    mode: str, corr: Corr, acct: PaperPerpsAccount, m: str, side: PerpSide, decided_at: datetime
) -> Decimal:
    """
    Collateral multiplier for a new position in ``m`` on ``side`` (plan, add-on 2).

    Args:
        mode (str): ``tiers`` or ``root``.
        corr (Corr): Correlations.
        acct (PaperPerpsAccount): The account; its open positions are the existing bets.
        m (str): Coin about to open.
        side (PerpSide): Its side.
        decided_at (datetime): Decision time.

    Returns:
        Decimal: 1 with nothing open; otherwise the tier or root multiplier.
    """
    signed = [
        (1.0 if p.side == side else -1.0) * corr.at(m, j, decided_at)
        for j, p in acct.positions.items()
    ]
    if not signed:
        return D(1)
    if mode == "tiers":
        r = sum(signed) / len(signed)
        return D(1) if r < 0.4 else D("0.85") if r < 0.6 else D("0.7") if r < 0.8 else D("0.5")
    if mode != "root":
        raise ValueError(f"unknown correlation sizing {mode!r}")
    total = max(sum(signed), 0.0)
    return max(D(str(round(1 / math.sqrt(1 + total), 4))), ROOT_FLOOR)


def stale(acct: PaperPerpsAccount, p: PerpPosition, price: Decimal, paid: Decimal) -> bool:
    """Whether ``p``, closed at ``price``, would not be in profit after every fee."""
    net = pnl_usd(p.side, p.size_usd, p.entry_price, price) - paid
    net -= fee_usd(p.size_usd, acct.params.close_fee_bps) + p.borrow_fees_usd
    return net <= 0


def run(
    params: PerpsParams,
    feed: lib.Feed,
    start: datetime,
    end: datetime,
    *,
    coins: tuple[str, ...] | list[str] | None = None,
    addons: Addons | None = None,
    corr: Corr | None = None,
) -> Outcome:
    """
    Replay one account over ``[start, end)`` with the add-ons that are switched on.

    Args:
        params (PerpsParams): Account settings; ``markets`` is replaced by ``coins``.
        feed (lib.Feed): Candles and caches.
        start (datetime): First bar.
        end (datetime): Bars opening at or after this are not used.
        coins: Coins traded, in the order the account walks them.
        addons (Addons | None): Switches; None is the baseline.
        corr (Corr | None): Shared correlations (built from the feed when omitted).

    Returns:
        Outcome: Result, how often the add-ons acted, and the size multipliers.
    """
    addons = addons or Addons()
    coins = tuple(coins or feed.coins)
    params = dataclasses.replace(params, markets={m: m for m in coins})
    sig, mov = feed.signals(), feed.moves()
    step = lib.STEP[feed.tf]
    times = feed.times[bisect.bisect_left(feed.times, start) : bisect.bisect_left(feed.times, end)]
    acct = PaperPerpsAccount.start(params, times[0])
    book = Book(addons)
    if addons.corr_sizing is not None and corr is None:
        corr = Corr(four_hour_candles(feed))
    limit = None if addons.time_limit_hours is None else timedelta(hours=addons.time_limit_hours)
    multipliers: list[float] = []
    last_time = {m: feed.order[m][-1] for m in coins}
    last_close: dict[str, Decimal] = {}
    daily: dict[date, float] = {}
    peak, max_dd = acct.cash_usd, D(0)
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
        book.read(acct)
        # Reason: a coin without the next bar keeps its last close as the mark and is skipped.
        px = dict(last_close)
        tradable = []
        for m in row:
            nxt = feed.rows[m].get(closes_at)
            if nxt is not None and n < len(times) - 1:
                px[m] = nxt[1]
                tradable.append(m)
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
                book.read(acct)
            book.signal_seen(m, target)
            cur = acct.positions.get(m)
            if (
                limit is not None
                and cur is not None
                and cur.tps_hit == 0
                and closes_at - cur.opened_at >= limit
                # Reason: with no take-profit yet, the trade's result so far is minus the
                # opening fee, so ``-book.pnl[m]`` is the fee already paid.
                and stale(acct, cur, px[m], -book.pnl[m])
            ):
                acct.close(m, px, closes_at, reason="TIME_LIMIT")
                book.read(acct)
                book.tl_block[m] = cur.side
                book.tl_exits += 1
            # Reason: the next three lines are ``PaperPerpsAccount.apply_signal``'s open.
            if target is None or m in acct.positions or m in acct.stopped_today:
                continue
            if book.waiting(m, target, closes_at):
                continue
            if corr is not None and addons.corr_sizing is not None:
                mult = multiplier(addons.corr_sizing, corr, acct, m, target, closes_at)
                acct.params = dataclasses.replace(
                    params,
                    max_collateral_per_position_pct=params.max_collateral_per_position_pct * mult,
                )
                if acct.open(m, target, px, closes_at).approved:
                    multipliers.append(float(mult))
                acct.params = params
            else:
                acct.open(m, target, px, closes_at)
            book.read(acct)
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
    acts = len(book.refused) + book.tl_exits + sum(1 for x in multipliers if x < 1)
    result = base.Result(base.summarize(acct, daily, max_dd, start, end), acct.events, daily)
    return Outcome(result, acts, multipliers)


def daily_returns(result: base.Result, start_equity: float) -> list[float]:
    """Day-to-day returns of a replay, the series ``summarize`` computes Sharpe from."""
    eq = [v for _, v in sorted(result.daily_equity.items())]
    return [b / a - 1 for a, b in zip([start_equity, *eq], eq, strict=False)]


def sharpe_difference(
    a: list[float], b: list[float], *, block: int = 10, draws: int = 2000, seed: int = 25
) -> tuple[float, float, float]:
    """
    Sharpe of ``a`` minus Sharpe of ``b`` with a 90% interval (paired block bootstrap).

    Args:
        a (list[float]): Daily returns of the variant.
        b (list[float]): Daily returns of the baseline on the same days.
        block (int): Block length in days.
        draws (int): Bootstrap draws.
        seed (int): Fixed seed, so every comparison on a slice resamples the same days.

    Returns:
        tuple[float, float, float]: Difference, 5th percentile, 95th percentile.

    Raises:
        ValueError: If the two series do not cover the same number of days.
    """
    if len(a) != len(b):
        raise ValueError("the two return series must cover the same days")
    x, y = np.asarray(a), np.asarray(b)
    n = len(x)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - block + 1, size=(draws, math.ceil(n / block)))
    # Reason: the same resampled days for both series keeps the comparison paired.
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, -1)[:, :n]

    def sharpe(v: Any) -> Any:
        return v.mean(axis=-1) / v.std(axis=-1, ddof=1) * math.sqrt(365)

    diffs = sharpe(x[idx]) - sharpe(y[idx])
    low, high = np.percentile(diffs, [5, 95])
    return float(sharpe(x) - sharpe(y)), float(low), float(high)
