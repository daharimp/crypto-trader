"""Order intent contract (contract 9)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import model_validator

from .common import DomainModel, SchemaVersion, UtcDatetime, VersionRef
from .enums import Environment, OrderPurpose, OrderType, Side


class OrderIntent(DomainModel):
    """An order the risk engine built from an approved RiskDecision."""

    schema_version: SchemaVersion
    order_intent_id: str
    correlation_id: str
    cycle_id: str
    idempotency_key: str
    risk_decision_id: str
    ensemble_decision_id: str
    signal_ids: list[str]
    strategy_versions: list[VersionRef]
    model_versions: list[VersionRef]
    instrument_id: str
    side: Side
    purpose: OrderPurpose
    order_type: OrderType
    quantity: Decimal
    reference_price: Decimal
    stop_price: Decimal | None
    attached_stop_distance_pct: Decimal | None
    parent_order_intent_id: str | None
    notional_estimate_usd: Decimal
    valid_until_utc: UtcDatetime
    environment: Environment
    funds: Literal["simulated", "real"]
    config_hash: str
    market_data_timestamp_utc: UtcDatetime
    decision_time_utc: UtcDatetime
    created_at_utc: UtcDatetime

    @model_validator(mode="after")
    def _shape(self) -> Self:
        """
        Enforce the side, type, and linkage rules for each purpose.

        Returns:
            OrderIntent: The validated intent.

        Raises:
            ValueError: If the intent shape is invalid.
        """
        if self.purpose == OrderPurpose.ENTRY:
            ok = self.side == Side.BUY and self.order_type == OrderType.MARKET
        elif self.purpose == OrderPurpose.EXIT:
            ok = self.side == Side.SELL and self.order_type == OrderType.MARKET
        else:
            ok = (
                self.side == Side.SELL
                and self.order_type == OrderType.STOP_MARKET
                and self.stop_price is not None
                and self.parent_order_intent_id is not None
            )
        if not ok:
            raise ValueError(f"invalid side/order_type for purpose {self.purpose}")
        if not self.signal_ids or not self.strategy_versions:
            raise ValueError("intents must reference signals and strategy versions (D-36)")
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if (self.funds == "real") != (self.environment == Environment.LIVE):
            raise ValueError("funds must be 'real' exactly in the live environment")
        return self
