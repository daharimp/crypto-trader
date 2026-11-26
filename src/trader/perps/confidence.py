"""Confidence score for a new paper perps position (ADR-054).

One number from 0 to 1 that says how much the wider picture agrees with a new position. The
risk code uses it to choose the position's size inside the owner's range
(``trader.perps.risk.collateral_pct``); it never decides whether to trade. It is the
composite that passed EXP-2026-026, the plain average of three readings:

- **breadth**: the share of the account's other markets whose signal is on the same side;
- **trend strength**: where the market's efficiency ratio (the number the live signal
  already uses to tell a trend from a range) stands among its own values at the previous
  540 4h closes;
- **timeframe agreement**: whether the 4h 50/200 averages and the last daily close against
  its 200-day average agree with the side.

Every reading uses only candles that had closed at the decision. Missing history counts as
0.5, neither for nor against, as in the experiment. Deterministic: no model, no network.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from trader.regimes.trend import EFFICIENCY_BARS, FAST, SLOW, efficiency_ratio

from .backtest import Bar
from .math import PerpSide

HALF = Decimal("0.5")
# Earlier 4h closes a percentile is measured against (90 days), and the fewest that count.
LOOKBACK = 540
MIN_EARLIER = 180
DAILY_SLOW = 200
# The 4h closes ``trend_strength`` reads: the lookback, the current one, and one window.
CLOSES_USED = LOOKBACK + 1 + EFFICIENCY_BARS


def breadth(side: PerpSide, others: Iterable[PerpSide | None]) -> Decimal:
    """
    Share of the account's other markets whose signal is on ``side``.

    Args:
        side (PerpSide): Side of the new position.
        others (Iterable[PerpSide | None]): The other markets' signals at this decision
            (None is flat).

    Returns:
        Decimal: 0 to 1; 0.5 when the account has no other market.
    """
    votes = list(others)
    if not votes:
        return HALF
    return Decimal(sum(1 for v in votes if v == side)) / len(votes)


def trend_strength(closes_4h: Sequence[Decimal]) -> Decimal:
    """
    Where the latest efficiency ratio stands among its previous ``LOOKBACK`` values.

    Args:
        closes_4h (Sequence[Decimal]): Completed 4h closes, oldest first.

    Returns:
        Decimal: 0 (the choppiest it has been) to 1 (the straightest); 0.5 with fewer than
        ``MIN_EARLIER`` earlier values or no reading now.
    """
    closes = list(closes_4h[-CLOSES_USED:])
    last = len(closes) - 1

    def ratio(i: int) -> Decimal | None:
        return efficiency_ratio(closes[max(0, i - EFFICIENCY_BARS) : i + 1])

    current = ratio(last) if last >= 0 else None
    if current is None:
        return HALF
    earlier = [v for i in range(max(0, last - LOOKBACK), last) if (v := ratio(i)) is not None]
    if len(earlier) < MIN_EARLIER:
        return HALF
    below = sum(1 for v in earlier if v < current)
    equal = sum(1 for v in earlier if v == current)
    return (Decimal(below) + Decimal(equal) / 2) / len(earlier)


def _mean(values: Sequence[Decimal], n: int) -> Decimal:
    return sum(values[-n:], Decimal(0)) / n


def timeframe_agreement(
    side: PerpSide, closes_4h: Sequence[Decimal], daily_closes: Sequence[Decimal]
) -> Decimal:
    """
    Share of two longer views that agree with ``side``.

    The views: the 4h SMA 50 against SMA 200, and the last completed daily close against the
    average of the last 200 daily closes. A view without enough history, or exactly level,
    counts as 0.5.

    Args:
        side (PerpSide): Side of the new position.
        closes_4h (Sequence[Decimal]): Completed 4h closes, oldest first.
        daily_closes (Sequence[Decimal]): Completed daily closes, oldest first.

    Returns:
        Decimal: 0, 0.25, 0.5, 0.75 or 1.
    """
    views: list[bool | None] = [None, None]
    if len(closes_4h) >= SLOW:
        fast, slow = _mean(closes_4h, FAST), _mean(closes_4h, SLOW)
        views[0] = None if fast == slow else fast > slow
    if len(daily_closes) >= DAILY_SLOW:
        average = _mean(daily_closes, DAILY_SLOW)
        views[1] = None if daily_closes[-1] == average else daily_closes[-1] > average
    long = side == PerpSide.LONG
    return sum((HALF if v is None else Decimal(int(v == long)) for v in views), Decimal(0)) / 2


def confidence(
    side: PerpSide,
    others: Iterable[PerpSide | None],
    closes_4h: Sequence[Decimal],
    daily_closes: Sequence[Decimal],
) -> Decimal:
    """
    The composite score for opening ``side``: the plain average of the three readings.

    Args:
        side (PerpSide): Side of the new position.
        others (Iterable[PerpSide | None]): The other markets' signals at this decision.
        closes_4h (Sequence[Decimal]): The market's completed 4h closes, oldest first.
        daily_closes (Sequence[Decimal]): The market's completed daily closes, oldest first.

    Returns:
        Decimal: 0 to 1.
    """
    parts = (
        breadth(side, others),
        trend_strength(closes_4h),
        timeframe_agreement(side, closes_4h, daily_closes),
    )
    return (parts[0] + parts[1] + parts[2]) / 3


def confidence_at(
    decided_at: datetime,
    side: PerpSide,
    others: Iterable[PerpSide | None],
    candles_4h: Sequence[Bar],
    candles_1d: Sequence[Bar],
) -> Decimal:
    """
    The composite score from candles, reading only those that had closed at the decision.

    Args:
        decided_at (datetime): Close time of the decision bar (UTC).
        side (PerpSide): Side of the new position.
        others (Iterable[PerpSide | None]): The other markets' signals at this decision.
        candles_4h (Sequence[Bar]): The market's 4h candles, oldest first (may include the
            forming one).
        candles_1d (Sequence[Bar]): The market's daily candles, oldest first (likewise).

    Returns:
        Decimal: 0 to 1.
    """
    four, day = timedelta(hours=4), timedelta(days=1)
    closes = [b.close for b in candles_4h if b.open_time_utc + four <= decided_at]
    days = [b.close for b in candles_1d if b.open_time_utc + day <= decided_at]
    return confidence(side, others, closes, days)
