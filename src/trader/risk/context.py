"""Inputs the risk engine evaluates against (§7.8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from trader.common.ids import IdGenerator
from trader.domain.compiled import CompiledProfile
from trader.domain.enums import Environment, OrderPurpose
from trader.domain.features import FeatureSet
from trader.domain.market import MarketSnapshot
from trader.domain.orders import OrderIntent
from trader.domain.positions import PositionSnapshot
from trader.domain.profiles import TradingProfile
from trader.domain.risk import LossState
from trader.domain.signals import SignalCandidate
from trader.domain.universe import UniverseSnapshot
from trader.execution.costs import CostParams
from trader.universe.registry import Registry

from .controls import RunControls
from .params import RiskParams


@dataclass
class RiskContext:
    """Everything one risk evaluation may read. Built fresh for each decision."""

    compiled: CompiledProfile
    profile: TradingProfile
    params: RiskParams | None
    registry: Registry
    costs: CostParams
    environment: Environment
    timeframe: str
    decision_time: datetime
    position: PositionSnapshot
    snapshot: MarketSnapshot
    features: FeatureSet | None
    universe: UniverseSnapshot | None
    signals: list[SignalCandidate]
    controls: RunControls
    loss: LossState
    ids: IdGenerator
    used_idempotency_keys: set[str] = field(default_factory=set)
    pending: list[OrderIntent] = field(default_factory=list)

    def held_quantity(self, instrument_id: str) -> Decimal:
        """
        Held quantity for an instrument.

        Args:
            instrument_id (str): Instrument.

        Returns:
            Decimal: Quantity (0 if flat).
        """
        for p in self.position.positions:
            if p.instrument_id == instrument_id:
                return p.quantity
        return Decimal(0)

    def market_value(self, instrument_id: str | None = None, tier: str | None = None) -> Decimal:
        """
        Market value of positions, optionally filtered.

        Args:
            instrument_id (str | None): Only this instrument.
            tier (str | None): Only this tier.

        Returns:
            Decimal: USD value.
        """
        return sum(
            (
                p.market_value_usd
                for p in self.position.positions
                if (instrument_id is None or p.instrument_id == instrument_id)
                and (tier is None or p.tier == tier)
            ),
            Decimal(0),
        )

    def pending_entries(self) -> list[OrderIntent]:
        """
        Unfilled entry market orders.

        Returns:
            list[OrderIntent]: Pending entries.
        """
        return [o for o in self.pending if o.purpose == OrderPurpose.ENTRY]

    def pending_notional(
        self, instrument_id: str | None = None, tier: str | None = None
    ) -> Decimal:
        """
        Notional of pending entries, optionally filtered.

        Args:
            instrument_id (str | None): Only this instrument.
            tier (str | None): Only this tier.

        Returns:
            Decimal: USD notional.
        """
        return sum(
            (
                o.notional_estimate_usd
                for o in self.pending_entries()
                if (instrument_id is None or o.instrument_id == instrument_id)
                and (tier is None or self.registry.tier_of(o.instrument_id) == tier)
            ),
            Decimal(0),
        )
