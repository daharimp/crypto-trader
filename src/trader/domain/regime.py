"""Regime assessment contract (contract 5)."""

from __future__ import annotations

from decimal import Decimal

from .common import DomainModel, SchemaVersion, UtcDatetime
from .enums import DataState, RegimeMethod, TrendState, VolatilityState


class RegimeAssessment(DomainModel):
    """Market regime for one instrument at a decision time."""

    schema_version: SchemaVersion
    regime_assessment_id: str
    instrument_id: str
    timeframe: str
    as_of_utc: UtcDatetime
    trend_state: TrendState
    volatility_state: VolatilityState
    data_state: DataState
    label: str
    confidence: Decimal | None
    method: RegimeMethod
    classifier_id: str
    classifier_version: str
    model_version: str | None
    feature_set_id: str | None
