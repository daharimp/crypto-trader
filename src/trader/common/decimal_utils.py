"""Decimal helpers (ADR-017): quantities round down to the instrument step."""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")
RATIO = Decimal("0.00000001")


def to_decimal(value: object) -> Decimal:
    """
    Convert a number or string to Decimal without binary float artefacts.

    Args:
        value (object): int, float, str, or Decimal.

    Returns:
        Decimal: Exact decimal value.

    Raises:
        TypeError: If the value is a bool or an unsupported type.
    """
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    raise TypeError(f"cannot convert {type(value).__name__} to Decimal")


def round_down_to_step(quantity: Decimal, step: Decimal) -> Decimal:
    """
    Round a quantity down to a multiple of the instrument step (never up).

    Args:
        quantity (Decimal): Raw quantity.
        step (Decimal): Instrument quantity step (> 0).

    Returns:
        Decimal: Largest multiple of ``step`` that is <= ``quantity`` (0 if negative).
    """
    if quantity <= 0:
        return Decimal("0")
    units = (quantity / step).to_integral_value(rounding=ROUND_DOWN)
    return (units * step).quantize(step)


def fmt_usd(value: Decimal) -> str:
    """
    Format a USD amount with 2 decimals (reporting only).

    Args:
        value (Decimal): Amount.

    Returns:
        str: e.g. ``"2500.00"``.
    """
    return format(value.quantize(CENT, rounding=ROUND_HALF_EVEN), "f")


def fmt_ratio(value: Decimal) -> str:
    """
    Format a ratio with 8 decimals (reporting only).

    Args:
        value (Decimal): Ratio.

    Returns:
        str: e.g. ``"0.12345678"``.
    """
    return format(value.quantize(RATIO, rounding=ROUND_HALF_EVEN), "f")
