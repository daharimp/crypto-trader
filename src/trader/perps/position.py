"""An open simulated perps position (ADR-025), kept apart from the account that holds it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .math import PerpSide


@dataclass
class PerpPosition:
    """An open simulated position."""

    market: str
    side: PerpSide
    size_usd: Decimal
    collateral_usd: Decimal
    entry_price: Decimal
    opened_at: datetime
    borrow_fees_usd: Decimal = Decimal(0)
    last_accrual: datetime | None = None
    # ADR-045 take-profit ladder: the opening stop price (R is its distance from entry), the
    # number of take-profits already hit, and the stop the ladder has moved to (None until
    # TP1; the collateral-based stop applies until then).
    initial_stop: Decimal | None = None
    tps_hit: int = 0
    moved_stop: Decimal | None = None
    # ADR-053: what the trade has realized so far, fees included: minus the opening fee, plus
    # the result of every take-profit. Added to the final close it says whether the whole
    # trade lost money. A position saved before ADR-053 starts from zero.
    realized_usd: Decimal = Decimal(0)
