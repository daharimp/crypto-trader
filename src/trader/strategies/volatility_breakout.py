"""``volatility_breakout`` 1.0.0: 20-bar channel breakout (strategy-spec §4.6)."""

from __future__ import annotations

from trader.domain.enums import Side
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import SignalCandidate

from .base import SignalIds, make_signal


class VolatilityBreakout:
    """Buy on a close above the prior 20-bar high; sell on a close below the prior 10-bar low."""

    strategy_id = "volatility_breakout"
    version = "1.0.0"

    def generate(
        self,
        snapshot: MarketSnapshot,
        features: FeatureSet,
        regime: RegimeAssessment,
        ids: SignalIds,
    ) -> list[SignalCandidate]:
        """
        Apply the channel rules.

        Args:
            snapshot (MarketSnapshot): Snapshot.
            features (FeatureSet): Features.
            regime (RegimeAssessment): Regime.
            ids (SignalIds): IDs.

        Returns:
            list[SignalCandidate]: One signal or none.
        """
        hi, lo = features.values.get("high_20_prev"), features.values.get("low_10_prev")
        if snapshot.latest_bar is None or hi is None or lo is None:
            return []
        close = snapshot.latest_bar.close
        if close > hi:
            return [
                make_signal(
                    self,
                    snapshot,
                    features,
                    regime,
                    ids,
                    Side.BUY,
                    "CLOSE_ABOVE_20_BAR_HIGH",
                    invalidation_reason="CLOSE_BELOW_10_BAR_LOW",
                )
            ]
        if close < lo:
            return [
                make_signal(
                    self, snapshot, features, regime, ids, Side.SELL, "CLOSE_BELOW_10_BAR_LOW"
                )
            ]
        return []
