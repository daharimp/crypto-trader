"""``sma_stance`` 1.0.0: hold long while SMA(50) is above SMA(200) (ADR-043, EXP-2026-018).

Unlike ``sma_trend`` (which buys only on the single bar where the fast average crosses up),
this rule buys on any bar while the uptrend holds, so a missed cross or a stop-out in an
uptrend does not leave the account idle until the next cross. Spot is long only: in a
downtrend it signals sell and stays in cash. Every entry still gets the risk engine's hard
stop (2 x ATR, UD-16); strategies never size orders or place stops.
"""

from __future__ import annotations

from decimal import Decimal

from trader.domain.enums import Side
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import SignalCandidate

from .base import SignalIds, make_signal

_SUPPORTED = {(50, 200): ("sma_50", "sma_200")}


class SmaStance:
    """Buy while fast > slow; signal sell while fast < slow."""

    strategy_id = "sma_stance"
    version = "1.0.0"

    def __init__(self, fast: int = 50, slow: int = 200) -> None:
        """
        Configure the averages.

        Args:
            fast (int): Fast period (must be 50).
            slow (int): Slow period (must be 200).

        Raises:
            ValueError: If the periods are not provided by the feature set.
        """
        if (fast, slow) not in _SUPPORTED:
            raise ValueError("sma_stance 1.0.0 requires fast=50, slow=200 (features-m2)")
        self.fast, self.slow = fast, slow
        self._keys = _SUPPORTED[(fast, slow)]

    def _gap(self, features: FeatureSet) -> Decimal | None:
        """Fast average relative to the slow one (``fast / slow - 1``), or None in warm-up."""
        f, s = (features.values.get(k) for k in self._keys)
        if f is None or s is None or s == 0:
            return None
        return f / s - 1

    def generate(
        self,
        snapshot: MarketSnapshot,
        features: FeatureSet,
        regime: RegimeAssessment,
        ids: SignalIds,
    ) -> list[SignalCandidate]:
        """
        Signal the current trend stance.

        Args:
            snapshot (MarketSnapshot): Snapshot.
            features (FeatureSet): Features.
            regime (RegimeAssessment): Regime (unused in 1.0.0).
            ids (SignalIds): IDs.

        Returns:
            list[SignalCandidate]: One signal, or none during warm-up.
        """
        gap = self._gap(features)
        if snapshot.latest_bar is None or gap is None:
            return []
        if gap > 0:
            return [
                make_signal(
                    self,
                    snapshot,
                    features,
                    regime,
                    ids,
                    Side.BUY,
                    "SMA50_ABOVE_SMA200",
                    invalidation_reason="SMA50_BELOW_SMA200",
                )
            ]
        if gap < 0:
            return [
                make_signal(self, snapshot, features, regime, ids, Side.SELL, "SMA50_BELOW_SMA200")
            ]
        return []

    def watch(self, features: FeatureSet | None, holding: bool) -> str:
        """
        One plain-English line on what the strategy is waiting for (dashboard, ADR-043).

        Args:
            features (FeatureSet | None): Latest features, or None if none were computed.
            holding (bool): Whether the account holds this coin.

        Returns:
            str: Status line.
        """
        gap = self._gap(features) if features is not None else None
        if gap is None:
            return "Warming up: needs 200 completed candles for the 200-candle average."
        pct = f"{abs(gap) * 100:.1f}%"
        if holding:
            if gap > 0:
                return f"Holding: uptrend, 50-candle average {pct} above the 200. Stop is set."
            return "Selling: the 50-candle average dropped below the 200."
        if gap > 0:
            return f"Uptrend (50-candle average {pct} above the 200): buys at the next check."
        return (
            f"Downtrend: 50-candle average {pct} below the 200. Spot is long only, so it "
            "waits in cash and buys when the 50 crosses back above the 200."
        )
