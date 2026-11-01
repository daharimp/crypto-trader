"""Position snapshot contract (contract 11)."""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import model_validator

from .common import DomainModel, SchemaVersion, UtcDatetime
from .enums import Sleeve


class PositionLine(DomainModel):
    """One open position."""

    instrument_id: str
    tier: str
    sleeve: Sleeve
    quantity: Decimal
    avg_entry_price: Decimal
    mark_price: Decimal
    market_value_usd: Decimal
    unrealized_pnl_usd: Decimal
    realized_pnl_usd: Decimal
    stop_price: Decimal | None
    opened_at_utc: UtcDatetime
    owner_strategy_ids: list[str]


class PositionSnapshot(DomainModel):
    """Portfolio state at a point in time."""

    schema_version: SchemaVersion
    position_snapshot_id: str
    as_of_utc: UtcDatetime
    cash_usd: Decimal
    committed_cash_usd: Decimal
    equity_usd: Decimal
    hwm_equity_usd: Decimal
    drawdown_pct: Decimal
    day_start_equity_usd: Decimal
    daily_pnl_pct: Decimal
    positions: list[PositionLine]
    exposure_by_instrument_pct: dict[str, Decimal]
    exposure_by_tier_pct: dict[str, Decimal]
    total_exposure_pct: Decimal
    open_positions_count: int
    breaker_open: bool
    daily_lockout_until_utc: UtcDatetime | None
    cooldowns: dict[str, UtcDatetime]

    @model_validator(mode="after")
    def _accounting(self) -> Self:
        """
        Enforce the accounting identity and spot long-only constraints.

        Returns:
            PositionSnapshot: The validated snapshot.

        Raises:
            ValueError: If equity, cash, or quantities are inconsistent.
        """
        if self.cash_usd < 0:
            raise ValueError("cash must be >= 0 (spot, no margin)")
        if any(p.quantity < 0 for p in self.positions):
            raise ValueError("quantities must be >= 0 (no short selling)")
        if self.equity_usd != self.cash_usd + sum(
            (p.market_value_usd for p in self.positions), Decimal("0")
        ):
            raise ValueError("equity must equal cash + market value")
        return self
