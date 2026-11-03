"""``tsmom`` 1.0.0: time-series momentum over 7 days (strategy-spec §4.4)."""

from __future__ import annotations

from trader.domain.enums import Side
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import SignalCandidate

from .base import SignalIds, make_signal


class Tsmom:
    """Buy when the 7-day return turns positive; sell while it is zero or negative."""

    strategy_id = "tsmom"
    version = "1.0.0"

    def __init__(self, lookback_days: int = 7) -> None:
        """
        Configure the strategy (features-m2 provides the 7-day return only).

        Args:
            lookback_days (int): Must be 7.

        Raises:
            ValueError: For any other lookback.
        """
        if lookback_days != 7:
            raise ValueError("tsmom 1.0.0 requires lookback_days=7 (features-m2)")

    def generate(
        self,
        snapshot: MarketSnapshot,
        features: FeatureSet,
        regime: RegimeAssessment,
        ids: SignalIds,
    ) -> list[SignalCandidate]:
        """
        Apply the momentum rule.

        Args:
            snapshot (MarketSnapshot): Snapshot.
            features (FeatureSet): Features.
            regime (RegimeAssessment): Regime.
            ids (SignalIds): IDs.

        Returns:
            list[SignalCandidate]: One signal or none.
        """
        r, rp = features.values.get("ret_7d"), features.values.get("ret_7d_prev")
        if snapshot.latest_bar is None or r is None or rp is None:
            return []
        if r > 0 and rp <= 0:
            return [
                make_signal(
                    self, snapshot, features, regime, ids, Side.BUY, "MOMENTUM_TURNED_POSITIVE"
                )
            ]
        if r <= 0:
            return [
                make_signal(
                    self, snapshot, features, regime, ids, Side.SELL, "MOMENTUM_NOT_POSITIVE"
                )
            ]
        return []
