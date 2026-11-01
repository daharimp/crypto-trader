"""``sma_trend`` 1.0.0: SMA(20)/SMA(50) trend baseline (handoff §7.7, R-09)."""

from __future__ import annotations

from decimal import Decimal

from trader.domain.enums import Side, Sleeve
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import Invalidation, SignalCandidate

from .base import SignalIds


class SmaTrend:
    """Buy on a fast-over-slow cross up; signal sell while fast is below slow."""

    strategy_id = "sma_trend"
    version = "1.0.0"

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        """
        Configure the strategy. ``features-m1`` only provides SMA 20 and 50.

        Args:
            fast (int): Fast period (must be 20).
            slow (int): Slow period (must be 50).

        Raises:
            ValueError: If the periods do not match the feature set.
        """
        if (fast, slow) != (20, 50):
            raise ValueError("sma_trend 1.0.0 requires fast=20, slow=50 (features-m1)")
        self.fast, self.slow = fast, slow

    def generate(
        self,
        snapshot: MarketSnapshot,
        features: FeatureSet,
        regime: RegimeAssessment,
        ids: SignalIds,
    ) -> list[SignalCandidate]:
        """
        Apply the cross rules at the decision time.

        Args:
            snapshot (MarketSnapshot): Snapshot.
            features (FeatureSet): Features.
            regime (RegimeAssessment): Regime (unused in 1.0.0).
            ids (SignalIds): IDs.

        Returns:
            list[SignalCandidate]: One signal or none.
        """
        v = features.values
        f, s, fp, sp = v.get("sma_20"), v.get("sma_50"), v.get("sma_20_prev"), v.get("sma_50_prev")
        if not features.warmup_complete or snapshot.latest_bar is None:
            return []
        if f is None or s is None or fp is None or sp is None:
            return []
        if f > s and fp <= sp:
            side, code = Side.BUY, "SMA_CROSS_UP"
        elif f < s:
            side, code = Side.SELL, "SMA_FAST_BELOW_SLOW"
        else:
            return []
        return [
            SignalCandidate(
                schema_version="1.0.0",
                signal_id=ids.signal_id,
                correlation_id=ids.correlation_id,
                cycle_id=ids.cycle_id,
                instrument_id=snapshot.instrument_id,
                timeframe=snapshot.timeframe,
                decision_time_utc=snapshot.as_of_utc,
                strategy_id=self.strategy_id,
                strategy_version=self.version,
                sleeve=Sleeve.CORE,
                side=side,
                strength=Decimal(1),
                confidence=None,
                expected_horizon=None,
                entry_reference_price=snapshot.latest_bar.close,
                invalidation=Invalidation(
                    kind="indicator_cross", level=None, reason="SMA_FAST_BELOW_SLOW"
                ),
                feature_set_id=features.feature_set_id,
                regime_assessment_id=regime.regime_assessment_id,
                model_id=None,
                model_version=None,
                rationale_codes=[code],
            )
        ]
