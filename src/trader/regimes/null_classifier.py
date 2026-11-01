"""Null regime classifier (M1 pass-through stage, D-29 step 2)."""

from __future__ import annotations

from trader.domain.enums import DataState, RegimeMethod, TrendState, VolatilityState
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment

CLASSIFIER_ID = "null_classifier"
CLASSIFIER_VERSION = "1.0.0"


def assess(
    snapshot: MarketSnapshot, features: FeatureSet | None, assessment_id: str
) -> RegimeAssessment:
    """
    Return an unknown regime; data state reflects snapshot freshness.

    Args:
        snapshot (MarketSnapshot): Snapshot.
        features (FeatureSet | None): Features (unused except for the ID).
        assessment_id (str): ID to assign.

    Returns:
        RegimeAssessment: Assessment with method ``not_evaluated``.
    """
    stale = not snapshot.is_fresh or snapshot.quality_status != "ok"
    return RegimeAssessment(
        schema_version="1.0.0",
        regime_assessment_id=assessment_id,
        instrument_id=snapshot.instrument_id,
        timeframe=snapshot.timeframe,
        as_of_utc=snapshot.as_of_utc,
        trend_state=TrendState.UNKNOWN,
        volatility_state=VolatilityState.UNKNOWN,
        data_state=DataState.STALE if stale else DataState.OK,
        label="unknown",
        confidence=None,
        method=RegimeMethod.NOT_EVALUATED,
        classifier_id=CLASSIFIER_ID,
        classifier_version=CLASSIFIER_VERSION,
        model_version=None,
        feature_set_id=features.feature_set_id if features else None,
    )
