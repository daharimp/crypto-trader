"""Execution report contract (contract 10)."""

from __future__ import annotations

from decimal import Decimal

from .common import DomainModel, SchemaVersion, UtcDatetime
from .enums import ExecutionStatus, ReasonCode


class ExecutionReport(DomainModel):
    """State of an order at a simulated adapter."""

    schema_version: SchemaVersion
    execution_report_id: str
    order_intent_id: str
    correlation_id: str
    adapter_id: str
    adapter_version: str
    venue: str
    status: ExecutionStatus
    reason_code: ReasonCode | None
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    expected_price: Decimal
    fees_usd: Decimal
    fee_rate_pct: Decimal
    slippage_bps_assumed: Decimal
    slippage_usd: Decimal
    submitted_at_utc: UtcDatetime
    filled_at_utc: UtcDatetime | None
    fill_bar_open_time_utc: UtcDatetime | None
    latency_ms: int
