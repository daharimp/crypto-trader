"""``random_entry`` 1.0.0: random-timing control (strategy-spec §4.7). Research only.

An edge has to beat this control under the same risk rules. Its timing is a deterministic
hash of (seed, instrument, decision time), so runs are reproducible and causal. It is never
eligible for paper or live sessions (``lifecycle_state: control``).
"""

from __future__ import annotations

from decimal import Decimal

from trader.common.clock import format_utc
from trader.common.hashing import sha256_hex
from trader.domain.enums import Side
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import SignalCandidate

from .base import SignalIds, make_signal


def _uniform(*parts: str) -> Decimal:
    """
    Deterministic uniform number in [0, 1) from text parts.

    Args:
        *parts (str): Inputs.

    Returns:
        Decimal: Pseudo-random value.
    """
    return Decimal(int(sha256_hex("|".join(parts))[:12], 16)) / Decimal(16**12)


class RandomEntry:
    """Buy with probability ``p_entry`` per bar, sell with probability ``p_exit`` per bar."""

    strategy_id = "random_entry"
    version = "1.0.0"

    def __init__(self, seed: int = 0, p_entry: float = 0.02, p_exit: float = 0.04) -> None:
        """
        Configure the control.

        Args:
            seed (int): Seed (vary it to build a distribution).
            p_entry (float): Per-bar entry probability (match the tested strategy's rate).
            p_exit (float): Per-bar exit probability (1 / mean holding bars).

        Raises:
            ValueError: If a probability is outside (0, 1).
        """
        if not (0 < p_entry < 1 and 0 < p_exit < 1):
            raise ValueError("p_entry and p_exit must be in (0, 1)")
        self.seed = str(seed)
        self.p_entry, self.p_exit = Decimal(str(p_entry)), Decimal(str(p_exit))

    def generate(
        self,
        snapshot: MarketSnapshot,
        features: FeatureSet,
        regime: RegimeAssessment,
        ids: SignalIds,
    ) -> list[SignalCandidate]:
        """
        Emit a random buy or sell; the ensemble acts only if it fits the position.

        Args:
            snapshot (MarketSnapshot): Snapshot.
            features (FeatureSet): Features (warm-up gate only).
            regime (RegimeAssessment): Regime.
            ids (SignalIds): IDs.

        Returns:
            list[SignalCandidate]: One signal or none.
        """
        if snapshot.latest_bar is None or not features.warmup_complete:
            return []
        t = format_utc(snapshot.as_of_utc)
        if _uniform(self.seed, snapshot.instrument_id, t, "entry") < self.p_entry:
            return [make_signal(self, snapshot, features, regime, ids, Side.BUY, "RANDOM_ENTRY")]
        if _uniform(self.seed, snapshot.instrument_id, t, "exit") < self.p_exit:
            return [make_signal(self, snapshot, features, regime, ids, Side.SELL, "RANDOM_EXIT")]
        return []
