"""Signal candidate contract (contract 6). Signals never carry size (D-32)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import Field

from .common import DomainModel, SchemaVersion, UtcDatetime
from .enums import Side, Sleeve


class Invalidation(DomainModel):
    """What would invalidate the signal."""

    kind: str
    level: Decimal | None
    reason: str


class SignalCandidate(DomainModel):
    """A strategy's directional opinion. No quantity, notional, leverage, or stop fields.

    Reason: ``extra="forbid"`` makes adding a size field a validation error, so strategies
    structurally cannot size orders (D-32, T-19).
    """

    schema_version: SchemaVersion
    signal_id: str
    correlation_id: str
    cycle_id: str
    instrument_id: str
    timeframe: str
    decision_time_utc: UtcDatetime
    strategy_id: str
    strategy_version: str
    sleeve: Sleeve
    side: Side
    strength: Annotated[Decimal, Field(ge=0, le=1)]
    confidence: Annotated[Decimal, Field(ge=0, le=1)] | None
    expected_horizon: str | None
    entry_reference_price: Decimal
    invalidation: Invalidation
    feature_set_id: str
    regime_assessment_id: str
    model_id: str | None
    model_version: str | None
    rationale_codes: list[str]
