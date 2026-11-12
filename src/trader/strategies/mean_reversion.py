"""``mean_reversion`` 1.0.0: RSI and Bollinger oversold entries (strategy-spec §4.5)."""

from __future__ import annotations

from decimal import Decimal

from trader.domain.enums import Side
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import SignalCandidate

from .base import SignalIds, make_signal

RSI_ENTRY, RSI_EXIT = Decimal(30), Decimal(50)


class MeanReversion:
    """Buy when RSI(14) < 30 and close < lower band; sell at the middle band or RSI > 50."""

    strategy_id = "mean_reversion"
    version = "1.0.0"

    def generate(
        self,
        snapshot: MarketSnapshot,
        features: FeatureSet,
        regime: RegimeAssessment,
        ids: SignalIds,
    ) -> list[SignalCandidate]:
        """
        Apply the oversold entry and reversion exit rules.

        Args:
            snapshot (MarketSnapshot): Snapshot.
            features (FeatureSet): Features.
            regime (RegimeAssessment): Regime.
            ids (SignalIds): IDs.

        Returns:
            list[SignalCandidate]: One signal or none.
        """
        v = features.values
        rsi, lower, mid = v.get("rsi_14"), v.get("bb_lower_20"), v.get("bb_mid_20")
        if snapshot.latest_bar is None or rsi is None or lower is None or mid is None:
            return []
        close = snapshot.latest_bar.close
        if rsi < RSI_ENTRY and close < lower:
            return [
                make_signal(
                    self,
                    snapshot,
                    features,
                    regime,
                    ids,
                    Side.BUY,
                    "OVERSOLD_BELOW_LOWER_BAND",
                    strength=(RSI_ENTRY - rsi) / 30,
                    invalidation_reason="REVERTED_TO_MID_OR_RSI_ABOVE_50",
                )
            ]
        if close >= mid or rsi > RSI_EXIT:
            return [
                make_signal(
                    self,
                    snapshot,
                    features,
                    regime,
                    ids,
                    Side.SELL,
                    "REVERTED_TO_MID_OR_RSI_ABOVE_50",
                )
            ]
        return []
