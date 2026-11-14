"""Pure Decimal arithmetic for perpetual positions (ADR-025).

The liquidation model mirrors the structure Jupiter Perps documents: a position is
liquidated when its remaining collateral (collateral + PnL - close fee - borrow fees)
falls to or below a maintenance requirement expressed as a share of position size. The
numeric thresholds come from configuration (UD-23), never from this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

BPS = Decimal(10_000)
ZERO = Decimal(0)


class PerpSide(StrEnum):
    """Direction of a perpetual position."""

    LONG = "long"
    SHORT = "short"


def leverage(size_usd: Decimal, collateral_usd: Decimal) -> Decimal:
    """
    Position leverage.

    Args:
        size_usd (Decimal): Notional position size in USD.
        collateral_usd (Decimal): Collateral posted in USD.

    Returns:
        Decimal: size / collateral.

    Raises:
        ValueError: If collateral is not positive.
    """
    if collateral_usd <= ZERO:
        raise ValueError("collateral must be > 0")
    return size_usd / collateral_usd


def pnl_usd(side: PerpSide, size_usd: Decimal, entry: Decimal, mark: Decimal) -> Decimal:
    """
    Unrealized profit or loss of a position.

    Args:
        side (PerpSide): Long or short.
        size_usd (Decimal): Notional size at entry.
        entry (Decimal): Entry price.
        mark (Decimal): Current mark price.

    Returns:
        Decimal: PnL in USD (negative is a loss).
    """
    move = (mark - entry) / entry
    return size_usd * move if side == PerpSide.LONG else -size_usd * move


def fee_usd(size_usd: Decimal, fee_bps: Decimal) -> Decimal:
    """
    Fee on a notional amount.

    Args:
        size_usd (Decimal): Notional in USD.
        fee_bps (Decimal): Fee in basis points.

    Returns:
        Decimal: Fee in USD.
    """
    return size_usd * fee_bps / BPS


def remaining_collateral(
    side: PerpSide,
    size_usd: Decimal,
    collateral_usd: Decimal,
    entry: Decimal,
    mark: Decimal,
    close_fee_bps: Decimal,
    borrow_fees_usd: Decimal,
) -> Decimal:
    """
    Collateral left if the position were closed at ``mark``.

    Args:
        side (PerpSide): Long or short.
        size_usd (Decimal): Notional size.
        collateral_usd (Decimal): Posted collateral.
        entry (Decimal): Entry price.
        mark (Decimal): Mark price.
        close_fee_bps (Decimal): Closing fee.
        borrow_fees_usd (Decimal): Borrow fees accrued so far.

    Returns:
        Decimal: Remaining collateral in USD (may be negative).
    """
    return (
        collateral_usd
        + pnl_usd(side, size_usd, entry, mark)
        - fee_usd(size_usd, close_fee_bps)
        - borrow_fees_usd
    )


def liquidation_price(
    side: PerpSide,
    size_usd: Decimal,
    collateral_usd: Decimal,
    entry: Decimal,
    close_fee_bps: Decimal,
    borrow_fees_usd: Decimal,
    maintenance_bps: Decimal,
) -> Decimal:
    """
    Mark price at which remaining collateral equals the maintenance requirement.

    Args:
        side (PerpSide): Long or short.
        size_usd (Decimal): Notional size.
        collateral_usd (Decimal): Posted collateral.
        entry (Decimal): Entry price.
        close_fee_bps (Decimal): Closing fee.
        borrow_fees_usd (Decimal): Borrow fees accrued so far.
        maintenance_bps (Decimal): Maintenance requirement as bps of size.

    Returns:
        Decimal: Liquidation price (0 for a long that cannot be liquidated above zero).
    """
    # Reason: solve collateral + side*size*(P/entry - 1) - fees = size*mm for P.
    buffer = (
        collateral_usd
        - fee_usd(size_usd, close_fee_bps)
        - borrow_fees_usd
        - fee_usd(size_usd, maintenance_bps)
    )
    frac = buffer / size_usd
    price = entry * (1 - frac) if side == PerpSide.LONG else entry * (1 + frac)
    return max(price, ZERO)


def is_liquidatable(
    side: PerpSide,
    size_usd: Decimal,
    collateral_usd: Decimal,
    entry: Decimal,
    mark: Decimal,
    close_fee_bps: Decimal,
    borrow_fees_usd: Decimal,
    maintenance_bps: Decimal,
) -> bool:
    """
    Whether the position is at or past liquidation at ``mark``.

    Args:
        side (PerpSide): Long or short.
        size_usd (Decimal): Notional size.
        collateral_usd (Decimal): Posted collateral.
        entry (Decimal): Entry price.
        mark (Decimal): Mark price.
        close_fee_bps (Decimal): Closing fee.
        borrow_fees_usd (Decimal): Borrow fees accrued so far.
        maintenance_bps (Decimal): Maintenance requirement as bps of size.

    Returns:
        bool: True when remaining collateral <= maintenance requirement.
    """
    rem = remaining_collateral(
        side, size_usd, collateral_usd, entry, mark, close_fee_bps, borrow_fees_usd
    )
    return rem <= fee_usd(size_usd, maintenance_bps)


# Volatility window for sizing (ADR-032): 30 days, the same window the owner was shown.
DAILY_MOVE_LOOKBACK_DAYS = 30


def typical_daily_move(closes: Sequence[Decimal], bars_per_day: int) -> Decimal | None:
    """
    Typical one-day price move as a fraction: the standard deviation of bar-to-bar returns
    over the last 30 days, scaled to one day.

    Args:
        closes (Sequence[Decimal]): Closes up to the decision bar, oldest first.
        bars_per_day (int): Bars in a day (6 for 4h candles, 24 for 1h).

    Returns:
        Decimal | None: For example ``Decimal("0.024")`` for 2.4% a day; None when there are
        fewer than 30 days of bars or the prices did not move.
    """
    n = DAILY_MOVE_LOOKBACK_DAYS * bars_per_day
    if bars_per_day < 1 or len(closes) < n + 1:
        return None
    window = closes[-(n + 1) :]
    rets = [b / a - 1 for a, b in zip(window, window[1:], strict=False)]
    mean = sum(rets, ZERO) / n
    var = sum(((r - mean) ** 2 for r in rets), ZERO) / (n - 1)
    move = (var * bars_per_day).sqrt()
    return move if move > 0 else None


def leverage_for_buffer(
    daily_move: Decimal,
    buffer_daily_moves: Decimal,
    close_fee_bps: Decimal,
    maintenance_bps: Decimal,
    ceiling: Decimal,
) -> Decimal:
    """
    Leverage that puts the liquidation price ``buffer_daily_moves`` typical daily moves away.

    A position is liquidated after an adverse move of about ``1 / leverage`` minus the
    closing fee and the maintenance requirement, so the leverage for a wanted distance is
    ``1 / (distance + fee + maintenance)``. The result is rounded down to one decimal and
    kept between 1 and ``ceiling``.

    Args:
        daily_move (Decimal): Typical daily move as a fraction (must be positive).
        buffer_daily_moves (Decimal): How many daily moves away liquidation must be.
        close_fee_bps (Decimal): Closing fee in bps of size.
        maintenance_bps (Decimal): Maintenance requirement in bps of size.
        ceiling (Decimal): Highest leverage allowed.

    Returns:
        Decimal: Leverage to open with.
    """
    distance = buffer_daily_moves * daily_move
    raw = 1 / (distance + (close_fee_bps + maintenance_bps) / BPS)
    return max(Decimal(1), min(ceiling, raw.quantize(Decimal("0.1"), rounding="ROUND_DOWN")))
