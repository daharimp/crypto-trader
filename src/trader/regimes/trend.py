"""Shared trend direction (ADR-043): one rule every bot reads to pick a side.

In a trending market: up while the 50-bar average is above the 200-bar average, down while
it is below. In a ranging market (the last 30 days of 4h candles moved less than 5% as far
net as they travelled, Kaufman efficiency ratio below 0.05) the faster 10/30 averages decide
instead (owner choice, EXP-2026-021).

Perps go long in an uptrend and short in a downtrend; spot, which stays long-only by the
safety rules, buys only in an uptrend, and the paper perps ``spot-perps`` account runs the
rule both ways at 1x. EXP-2026-019 and EXP-2026-020 picked 50/200: it was the only
long+short rule tested that made money on held-back data in both experiments.
"""

from __future__ import annotations

from decimal import Decimal

from trader.domain.enums import TrendState

FAST = 50
SLOW = 200
# Ranging-market switch (ADR-043, EXP-2026-021). Lengths are 4h candles (6 a day).
RANGE_FAST = 10
RANGE_SLOW = 30
EFFICIENCY_BARS = 180  # 30 days
RANGE_EFFICIENCY_BELOW = Decimal("0.05")


def trend_state(fast_avg: Decimal | None, slow_avg: Decimal | None) -> TrendState:
    """
    Trend from the two averages.

    Args:
        fast_avg (Decimal | None): 50-bar average, or None while warming up.
        slow_avg (Decimal | None): 200-bar average, or None while warming up.

    Returns:
        TrendState: ``TRENDING_UP``, ``TRENDING_DOWN``, or ``UNKNOWN`` while warming up or
        when the averages are equal.
    """
    if fast_avg is None or slow_avg is None or fast_avg == slow_avg:
        return TrendState.UNKNOWN
    return TrendState.TRENDING_UP if fast_avg > slow_avg else TrendState.TRENDING_DOWN


def _mean(values: list[Decimal], n: int) -> Decimal | None:
    if len(values) < n:
        return None
    return sum(values[-n:], Decimal(0)) / n


def efficiency_ratio(closes: list[Decimal], n: int = EFFICIENCY_BARS) -> Decimal | None:
    """
    Kaufman efficiency ratio: net move over the path travelled in the last ``n`` bars.

    Args:
        closes (list[Decimal]): Closes, oldest first.
        n (int): Bars to measure.

    Returns:
        Decimal | None: 0 (pure chop) to 1 (a straight line); None with too few closes or no
        movement at all.
    """
    if n < 1 or len(closes) <= n:
        return None
    window = closes[-n - 1 :]
    path = sum((abs(b - a) for a, b in zip(window, window[1:], strict=False)), Decimal(0))
    if path == 0:
        return None
    return abs(window[-1] - window[0]) / path


def is_ranging(closes: list[Decimal]) -> bool:
    """
    Whether the market is ranging: efficiency ratio below ``RANGE_EFFICIENCY_BELOW``.

    Args:
        closes (list[Decimal]): Closes, oldest first.

    Returns:
        bool: True when ranging; False when trending or not measurable.
    """
    er = efficiency_ratio(closes)
    return er is not None and er < RANGE_EFFICIENCY_BELOW


def trend_from_closes(closes: list[Decimal]) -> TrendState:
    """
    Direction from closes up to the decision bar (never looks ahead).

    Args:
        closes (list[Decimal]): Closes, oldest first.

    Returns:
        TrendState: ``TRENDING_UP`` or ``TRENDING_DOWN`` from the 50/200 averages, or from the
        10/30 averages while ranging; ``UNKNOWN`` with fewer than ``SLOW`` closes or equal
        averages.
    """
    if len(closes) < SLOW:
        return TrendState.UNKNOWN
    if is_ranging(closes):
        # Reason: in chop the slow pair lags whole swings; the owner chose the fast pair
        # there (EXP-2026-021: ER<0.05 -> 10/30, a little better in both periods).
        return trend_state(_mean(closes, RANGE_FAST), _mean(closes, RANGE_SLOW))
    return trend_state(_mean(closes, FAST), _mean(closes, SLOW))
