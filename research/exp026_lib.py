"""EXP-2026-026 harness: confidence scores at each entry, and size chosen inside a range.

Research only (plan: ``research/EXP-2026-026-plan.md``). The replay loop is a copy of the
ungrouped path of ``exp024_lib.run`` with ``apply_signal`` written out, so that for each new
position it can (1) record the confidence scores at that decision and (2) set that
position's collateral through the real paper account. With no sizer it must reproduce
``exp024_lib.run`` event for event (``run_exp026.py check``).

Every score is read from 4h candles that have closed at the decision time (open + 4h at or
before it), also for the hourly account, whose signal itself looks at the forming candle:
- M1 breadth: share of the account's other coins (those with a bar at the decision) whose
  signal is on the new position's side.
- M2 trend strength: percentile of the coin's Kaufman efficiency ratio (180 4h closes,
  ``trader.regimes.trend.efficiency_ratio``, the live signal's own number) among its values
  at the previous 540 4h closes.
- M3 timeframe agreement: share of two views that agree with the side, the 4h SMA 50
  against SMA 200 and the last finished UTC day's close against its 200-day average.
- M4 distance from the slow average: percentile, as M2, of |close - SMA 200| / close. The
  raw percentile is recorded; its direction is fixed on slice A1 by the run script.
- MC: the plain average of M1, M2 and M3.
"""

from __future__ import annotations

import bisect
import dataclasses
import os
import pickle
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as base
import exp024_lib as lib
import numpy as np

from trader.perps.math import PerpSide
from trader.perps.params import PerpsParams
from trader.perps.simulator import PaperPerpsAccount
from trader.regimes.trend import EFFICIENCY_BARS, FAST, SLOW, efficiency_ratio

D = Decimal
HALF = D("0.5")
LOOKBACK = 540  # earlier 4h closes a percentile is measured against (90 days)
MIN_EARLIER = 180  # with fewer earlier values the score is 0.5
DAILY_SLOW = 200
MEASURES = ("M1", "M2", "M3", "M4", "MC")
Scores = dict[str, Decimal]
Sizer = Callable[[Scores], Decimal]


@dataclass
class CoinFeatures:
    """Per completed 4h candle of one coin: the numbers the scores are read from."""

    opens: list[datetime]
    er: list[Decimal | None]
    dist: list[Decimal | None]
    fast_above: list[bool | None]  # SMA 50 above SMA 200; None while warming up or equal
    day_done: list[datetime]  # the midnight that ends each UTC day with candles
    day_above: list[bool | None]  # that day's close above its 200-day average


def coin_features(candles: list[base.Row]) -> CoinFeatures:
    """Build the per-candle numbers for one coin from its 4h candles (ascending)."""
    closes = [r[4] for r in candles]
    csum = [D(0)]
    for c in closes:
        csum.append(csum[-1] + c)
    er: list[Decimal | None] = []
    dist: list[Decimal | None] = []
    fast_above: list[bool | None] = []
    for i, c in enumerate(closes):
        # Reason: the same function and window the live signal uses to call a range.
        er.append(efficiency_ratio(closes[max(0, i - EFFICIENCY_BARS) : i + 1]))
        slow = (csum[i + 1] - csum[i + 1 - SLOW]) / SLOW if i + 1 >= SLOW else None
        fast = (csum[i + 1] - csum[i + 1 - FAST]) / FAST if i + 1 >= FAST else None
        dist.append(None if slow is None else abs(c - slow) / c)
        known = slow is not None and fast is not None and fast != slow
        fast_above.append(fast > slow if known else None)  # type: ignore[operator]
    # Reason: a candle belongs to the UTC day its close falls in (the 20:00 candle closes at
    # midnight and is that day's last); the day is finished at the following midnight.
    days: dict[date, Decimal] = {}
    for r in candles:
        days[(r[0] + base.TREND_STEP - timedelta(seconds=1)).date()] = r[4]
    day_done, day_above, dclose = [], [], []
    for day, close in sorted(days.items()):
        dclose.append(close)
        day_done.append(datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1))
        if len(dclose) < DAILY_SLOW:
            day_above.append(None)
        else:
            avg = sum(dclose[-DAILY_SLOW:], D(0)) / DAILY_SLOW
            day_above.append(None if close == avg else close > avg)
    return CoinFeatures([r[0] for r in candles], er, dist, fast_above, day_done, day_above)


def candles_4h(feed: lib.Feed, m: str) -> list[base.Row]:
    """The coin's 4h candles: the trend candles of an hourly feed, else the feed's own."""
    if feed.trend is not None:
        return feed.trend[m]
    return [feed.rows[m][t] for t in feed.order[m]]


def features(feed: lib.Feed, cache_dir: Path | None = None) -> dict[str, CoinFeatures]:
    """Per-coin features, cached on disk and stamped with the 4h file's size and last time."""
    out: dict[str, CoinFeatures] = {}
    for m in feed.coins:
        candles = candles_4h(feed, m)
        stamp = (len(candles), candles[-1][0])
        path = cache_dir / f"feat-{m.lower()}.pkl" if cache_dir else None
        got: CoinFeatures | None = None
        if path is not None and path.exists():
            with open(path, "rb") as f:
                saved, cached = pickle.load(f)  # noqa: S301 - our own cache file
            got = cached if saved == stamp else None
        if got is None:
            got = coin_features(candles)
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Reason: several jobs may run at once; each writes its own temporary file.
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                with open(tmp, "wb") as f:
                    pickle.dump((stamp, got), f)
                tmp.replace(path)
        out[m] = got
    return out


def percentile(values: list[Decimal | None], i: int) -> Decimal:
    """Where ``values[i]`` stands among the previous ``LOOKBACK`` values (0 lowest, 1 highest)."""
    if i < 0 or values[i] is None:
        return HALF
    cur = values[i]
    earlier = [v for v in values[max(0, i - LOOKBACK) : i] if v is not None]
    if len(earlier) < MIN_EARLIER:
        return HALF
    below = sum(1 for v in earlier if v < cur)  # type: ignore[operator]
    equal = sum(1 for v in earlier if v == cur)
    return (D(below) + D(equal) / 2) / len(earlier)


@dataclass
class Scorer:
    """Confidence scores for a new position, from candles completed at the decision."""

    feed: lib.Feed
    coins: tuple[str, ...]
    sig: dict[str, lib.Series]
    feats: dict[str, CoinFeatures]

    def at(self, m: str, side: PerpSide, t: datetime, decided: datetime) -> Scores:
        """
        Scores for opening ``side`` in ``m`` at the decision taken when bar ``t`` closes.

        Args:
            m (str): Coin.
            side (PerpSide): Side of the new position.
            t (datetime): Open time of the bar whose close is the decision.
            decided (datetime): The decision time (that bar's close).

        Returns:
            Scores: M1, M2, M3, M4 (raw percentile) and MC, each between 0 and 1.
        """
        f = self.feats[m]
        # Reason: only 4h candles with open + 4h <= the decision are complete.
        i = bisect.bisect_right(f.opens, decided - base.TREND_STEP) - 1
        others = [o for o in self.coins if o != m and t in self.feed.rows[o]]
        agree = sum(1 for o in others if self.sig[o].get(t) == side)
        m1 = D(agree) / len(others) if others else HALF
        k = bisect.bisect_right(f.day_done, decided) - 1
        long = side == PerpSide.LONG
        views = [f.fast_above[i] if i >= 0 else None, f.day_above[k] if k >= 0 else None]
        m3 = sum((HALF if v is None else D(int(v == long)) for v in views), D(0)) / len(views)
        m2 = percentile(f.er, i)
        return {
            "M1": m1,
            "M2": m2,
            "M3": m3,
            "M4": percentile(f.dist, i),
            "MC": (m1 + m2 + m3) / 3,
        }


@dataclass
class Entry:
    """One opened position: where, when, its scores and the collateral % it was given."""

    market: str
    side: str
    at_utc: str
    scores: Scores
    pct: Decimal


def run(
    params: PerpsParams,
    feed: lib.Feed,
    start: datetime,
    end: datetime,
    *,
    coins: tuple[str, ...] | list[str],
    scorer: Scorer | None = None,
    sizer: Sizer | None = None,
) -> tuple[base.Result, list[Entry]]:
    """
    Replay one account over ``[start, end)``; optionally score and size every new position.

    Args:
        params (PerpsParams): Account settings; ``markets`` is replaced by ``coins``.
        feed (lib.Feed): Candles and caches.
        start (datetime): First bar.
        end (datetime): Bars opening at or after this are not used.
        coins: Coins traded, in the order the account walks them.
        scorer (Scorer | None): Records the scores of every opened position.
        sizer (Sizer | None): Scores -> collateral % of equity for that position (needs
            ``scorer``); flat sizing from ``params`` when omitted.

    Returns:
        tuple[base.Result, list[Entry]]: Stats, events, daily equity; and the entries.
    """
    coins = tuple(coins)
    params = dataclasses.replace(params, markets={m: m for m in coins})
    sig, mov, step = feed.signals(), feed.moves(), base.STEP[feed.tf]
    times = feed.times[bisect.bisect_left(feed.times, start) : bisect.bisect_left(feed.times, end)]
    acct = PaperPerpsAccount.start(params, times[0])
    last_time = {m: feed.order[m][-1] for m in coins}
    last_close: dict[str, Decimal] = {}
    daily: dict[date, float] = {}
    entries: list[Entry] = []
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
                    is_long = p.side == PerpSide.LONG
                    marks[m] = row[m][3] if is_long else row[m][2]
                    favorable[m] = row[m][2] if is_long else row[m][3]
            acct.mark(
                marks,
                closes_at,
                opens={m: r[1] for m, r in row.items()},
                favorable=favorable,
                closes=dict(last_close),
            )
        elif n > 0:
            acct.mark(dict(last_close), closes_at)
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
            # Reason: PaperPerpsAccount.apply_signal written out, so the open can be sized.
            cur = acct.positions.get(m)
            if cur is not None and cur.side != target:
                acct.close(m, px, closes_at, reason="SIGNAL_CHANGED")
            if target is None or m in acct.positions or m in acct.stopped_today:
                continue
            scores = scorer.at(m, target, t, closes_at) if scorer is not None else {}
            pct = params.max_collateral_per_position_pct
            if sizer is not None:
                pct = sizer(scores)
                acct.params = dataclasses.replace(params, max_collateral_per_position_pct=pct)
            decision = acct.open(m, target, px, closes_at)
            acct.params = params
            if decision.approved and scorer is not None:
                entries.append(Entry(m, target.value, closes_at.isoformat(), scores, pct))
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
    result = base.Result(base.summarize(acct, daily, max_dd, start, end), acct.events, daily)
    return result, entries


def trade_results(
    events: list[dict[str, Any]], stop_share: Decimal
) -> dict[tuple[str, str], tuple[float, str]]:
    """
    Result of every trade in R, keyed by (market, time opened).

    R is the whole trade's profit or loss after every fee (opening fee, take-profit
    proceeds and fees, closing P&L and fees including borrow) over the planned loss at the
    opening stop (collateral at the open x the stop share). A liquidation loses the
    collateral still posted.

    Args:
        events (list[dict[str, Any]]): The account's events, in order.
        stop_share (Decimal): Stop-loss share of collateral, as a fraction.

    Returns:
        dict: ``(market, opened at) -> (R, how it closed)``.
    """
    live: dict[str, tuple[str, Decimal, Decimal]] = {}  # market -> (opened at, collateral, pnl)
    out: dict[tuple[str, str], tuple[float, str]] = {}
    for e in events:
        m = e.get("market")
        if e["event"] == "OPENED":
            live[m] = (e["at_utc"], D(e["collateral_usd"]), -D(e["fee_usd"]))
        elif e["event"] == "TAKE_PROFIT":
            at, coll, pnl = live[m]
            live[m] = (at, coll, pnl + D(e["pnl_usd"]) - D(e["fees_usd"]))
        elif e["event"] in ("CLOSED", "LIQUIDATED"):
            at, coll, pnl = live.pop(m)
            if e["event"] == "CLOSED":
                pnl += D(e["pnl_usd"]) - D(e["fees_usd"])
            else:
                pnl -= D(e["collateral_lost_usd"])
            out[(m, at)] = (float(pnl / (coll * stop_share)), e.get("reason", "LIQUIDATED"))
    return out


def ranks(x: np.ndarray) -> np.ndarray:
    """Average ranks (ties share their mean rank)."""
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    r[order] = np.arange(len(x), dtype=float)
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts))
    np.add.at(sums, inv, r)
    return np.asarray(sums[inv] / counts[inv])


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Rank correlation; 0 when either side does not vary."""
    if len(x) < 3:
        return 0.0
    rx, ry = ranks(x), ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def thirds(score: np.ndarray, r: np.ndarray) -> tuple[list[tuple[int, float, float]], str]:
    """
    Entries, mean R and share of winners in the bottom, middle and top third by score.

    Ties stay together (an entry's place is its mid-rank). A score with three or fewer
    distinct values is split at its natural levels instead: lowest, middle (if any), highest.

    Args:
        score (np.ndarray): Score per entry.
        r (np.ndarray): Result in R per entry.

    Returns:
        tuple: Three ``(entries, mean R, win share)`` rows (zeros for an empty group) and a
        note naming the levels when natural levels were used.
    """
    levels = np.unique(score)
    note = ""
    if len(levels) <= 3:
        group = np.full(len(score), 1)
        group[score == levels[0]] = 0
        if len(levels) > 1:
            group[score == levels[-1]] = 2
        note = "levels " + "/".join(f"{v:.2f}" for v in levels)
    else:
        place = ranks(score) + 0.5  # mid-rank, 0.5 .. n - 0.5
        frac = place / len(score)
        group = np.where(frac < 1 / 3, 0, np.where(frac >= 2 / 3, 2, 1))
    rows = []
    for g in (0, 1, 2):
        sel = r[group == g]
        rows.append(
            (len(sel), float(sel.mean()), float((sel > 0).mean())) if len(sel) else (0, 0.0, 0.0)
        )
    return rows, note


def week_interval(
    score: np.ndarray,
    r: np.ndarray,
    weeks: list[tuple[int, int]],
    draws: int = 2000,
    seed: int = 26,
) -> tuple[float, float]:
    """90% interval of the rank correlation, resampling whole calendar weeks of entries."""
    by_week: dict[tuple[int, int], list[int]] = {}
    for i, w in enumerate(weeks):
        by_week.setdefault(w, []).append(i)
    groups = [np.array(v) for v in by_week.values()]
    rng = np.random.default_rng(seed)
    got = []
    for _ in range(draws):
        pick = np.concatenate([groups[j] for j in rng.integers(0, len(groups), len(groups))])
        got.append(spearman(score[pick], r[pick]))
    lo, hi = np.percentile(got, [5, 95])
    return float(lo), float(hi)


def daily_returns(result: base.Result, start_balance: float) -> np.ndarray:
    """Day-to-day returns of a replay, the first from the starting balance."""
    eq = [v for _, v in sorted(result.daily_equity.items())]
    return np.array([b / a - 1 for a, b in zip([start_balance, *eq], eq, strict=False)])


def sharpe(rets: np.ndarray) -> float:
    """Daily Sharpe on a 365-day year."""
    sd = rets.std(ddof=1)
    return float(rets.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0


def sharpe_diff_interval(
    a: np.ndarray, b: np.ndarray, block: int = 10, draws: int = 2000, seed: int = 26
) -> tuple[float, float]:
    """90% interval of Sharpe(a) - Sharpe(b), the same 10-day blocks drawn for both series."""
    n = len(a)
    rng = np.random.default_rng(seed)
    reach = np.arange(block)
    got = []
    for _ in range(draws):
        starts = rng.integers(0, n - block + 1, int(np.ceil(n / block)))
        idx = (starts[:, None] + reach).ravel()[:n]
        got.append(sharpe(a[idx]) - sharpe(b[idx]))
    lo, hi = np.percentile(got, [5, 95])
    return float(lo), float(hi)
