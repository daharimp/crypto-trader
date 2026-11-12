"""Strategy interface. Strategies emit SignalCandidates only; they never size (D-32)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from trader.domain.enums import Side, Sleeve
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import Invalidation, SignalCandidate


@dataclass(frozen=True)
class SignalIds:
    """IDs a strategy attaches to its signals."""

    signal_id: str
    correlation_id: str
    cycle_id: str


class Strategy(Protocol):
    """A rule-based strategy."""

    strategy_id: str
    version: str

    def generate(
        self,
        snapshot: MarketSnapshot,
        features: FeatureSet,
        regime: RegimeAssessment,
        ids: SignalIds,
    ) -> list[SignalCandidate]:
        """
        Produce zero or more signals at the snapshot's decision time.

        Args:
            snapshot (MarketSnapshot): Point-in-time market view.
            features (FeatureSet): Causal features.
            regime (RegimeAssessment): Regime assessment.
            ids (SignalIds): IDs to use.

        Returns:
            list[SignalCandidate]: Signals (no size fields).
        """
        ...


def make_signal(
    strategy: Strategy,
    snapshot: MarketSnapshot,
    features: FeatureSet,
    regime: RegimeAssessment,
    ids: SignalIds,
    side: Side,
    code: str,
    strength: Decimal = Decimal(1),
    invalidation_reason: str = "STRATEGY_EXIT_RULE",
) -> SignalCandidate:
    """
    Build a SignalCandidate with the fields every rule-based baseline shares.

    Args:
        strategy (Strategy): Emitting strategy.
        snapshot (MarketSnapshot): Snapshot (must have a latest bar).
        features (FeatureSet): Features.
        regime (RegimeAssessment): Regime.
        ids (SignalIds): IDs.
        side (Side): ``buy`` or ``sell``.
        code (str): Rationale code.
        strength (Decimal): Strength in [0, 1].
        invalidation_reason (str): Invalidation reason code.

    Returns:
        SignalCandidate: Signal (no size fields, D-32).
    """
    assert snapshot.latest_bar is not None
    return SignalCandidate(
        schema_version="1.0.0",
        signal_id=ids.signal_id,
        correlation_id=ids.correlation_id,
        cycle_id=ids.cycle_id,
        instrument_id=snapshot.instrument_id,
        timeframe=snapshot.timeframe,
        decision_time_utc=snapshot.as_of_utc,
        strategy_id=strategy.strategy_id,
        strategy_version=strategy.version,
        sleeve=Sleeve.CORE,
        side=side,
        strength=min(max(strength, Decimal(0)), Decimal(1)),
        confidence=None,
        expected_horizon=None,
        entry_reference_price=snapshot.latest_bar.close,
        invalidation=Invalidation(kind="indicator_rule", level=None, reason=invalidation_reason),
        feature_set_id=features.feature_set_id,
        regime_assessment_id=regime.regime_assessment_id,
        model_id=None,
        model_version=None,
        rationale_codes=[code],
    )
