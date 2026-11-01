"""Strategy interface. Strategies emit SignalCandidates only; they never size (D-32)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import SignalCandidate


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
