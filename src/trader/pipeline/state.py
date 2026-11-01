"""Mutable state of one backtest run, shared by the cycle and the runner."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from trader.common.ids import IdGenerator
from trader.data.snapshots import SnapshotBuilder
from trader.domain.compiled import CompiledProfile
from trader.domain.enums import Environment, EventType, OrderPurpose, Side
from trader.domain.orders import OrderIntent
from trader.domain.positions import PositionSnapshot
from trader.domain.profiles import TradingProfile
from trader.domain.risk import RiskDecision
from trader.execution.costs import CostParams
from trader.execution.service import ExecutionService
from trader.journal.store import JournalStore
from trader.portfolio.ledger import Ledger
from trader.risk.controls import RunControls
from trader.risk.engine import RiskEngine
from trader.risk.loss_state import LossTracker
from trader.risk.params import RiskParams
from trader.strategies.base import Strategy
from trader.universe.eligibility import EligibilityEvaluator
from trader.universe.registry import Registry


@dataclass
class RunState:
    """Everything a decision cycle reads or changes."""

    compiled: CompiledProfile
    profile: TradingProfile
    params: RiskParams | None
    registry: Registry
    costs: CostParams
    environment: Environment
    timeframe: str
    builder: SnapshotBuilder
    eligibility: EligibilityEvaluator
    strategy: Strategy
    # Reason: the simulator in backtests and paper; the Kraken adapter in live (same protocol).
    adapter: Any
    execution: ExecutionService
    ledger: Ledger
    loss: LossTracker
    journal: JournalStore
    controls: RunControls = field(default_factory=RunControls)
    engine: RiskEngine = field(default_factory=RiskEngine)
    ids: IdGenerator = field(default_factory=IdGenerator)
    used_keys: set[str] = field(default_factory=set)
    pending: dict[str, OrderIntent] = field(default_factory=dict)
    stops: dict[str, OrderIntent] = field(default_factory=dict)
    decisions: dict[str, RiskDecision] = field(default_factory=dict)
    filled_entries: set[str] = field(default_factory=set)
    counts: Counter[str] = field(default_factory=Counter)
    rejections: Counter[str] = field(default_factory=Counter)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    exposure_curve: list[Decimal] = field(default_factory=list)
    # Forward-session hooks (BL-027). Backtests leave them unset.
    on_kill_switch: Callable[[str, str], None] | None = None
    on_event: Callable[[EventType, Any], None] | None = None
    reconcile_fn: Callable[[Ledger, dict[str, Decimal]], list[str]] | None = None
    owner_flatten_decision_ids: set[str] = field(default_factory=set)

    def committed_cash(self) -> Decimal:
        """
        Cash committed to pending buy orders, including fees.

        Returns:
            Decimal: Committed USD.
        """
        return sum(
            (
                o.notional_estimate_usd * (1 + self.costs.fee_rate)
                for o in self.pending.values()
                if o.side == Side.BUY and o.purpose == OrderPurpose.ENTRY
            ),
            Decimal(0),
        )

    def position_snapshot(self, t: object) -> PositionSnapshot:
        """
        Build the current PositionSnapshot.

        Args:
            t (object): As-of time (datetime).

        Returns:
            PositionSnapshot: Snapshot.
        """
        cds = {k: v for k, v in self.controls.cooldowns.until.items()}
        return self.ledger.snapshot(
            self.ids.next("pos"),
            t,  # type: ignore[arg-type]
            self.committed_cash(),
            self.loss.hwm,
            self.loss.day_start,
            self.controls.breaker.open,
            self.controls.lockout.until,
            cds,
        )
