"""Risk decision contract (contract 8)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import model_validator

from .common import DomainModel, SchemaVersion, UtcDatetime
from .enums import BindingConstraint, ReasonCode, RiskStatus, RuleOutcome


class RuleResult(DomainModel):
    """Outcome of one risk rule."""

    rule_id: str
    rule_version: str
    outcome: RuleOutcome
    reason_code: ReasonCode | None
    detail: dict[str, str]


class LossState(DomainModel):
    """Portfolio loss state used by the loss rules (D-12)."""

    equity_usd: Decimal
    hwm_equity_usd: Decimal
    drawdown_pct: Decimal
    day_start_equity_usd: Decimal
    daily_pnl_pct: Decimal
    loss_scaling_multiplier: Decimal
    breaker_open: bool
    daily_lockout_active: bool


class StopSpec(DomainModel):
    """Protective stop chosen by the risk engine (strategies never set stops)."""

    method: str
    stop_distance_pct: Decimal
    atr_value: Decimal | None


class RiskDecision(DomainModel):
    """Deterministic approve / modify / reject decision with every rule result."""

    schema_version: SchemaVersion
    risk_decision_id: str
    correlation_id: str
    cycle_id: str
    ensemble_decision_id: str
    instrument_id: str
    decision_time_utc: UtcDatetime
    action_evaluated: Literal["enter_long", "exit_long"]
    status: RiskStatus
    approved_quantity: Decimal
    approved_notional_usd: Decimal
    reference_price: Decimal
    stop: StopSpec | None
    loss_state: LossState
    rule_results: list[RuleResult]
    reason_codes: list[ReasonCode]
    binding_constraint: BindingConstraint | None
    config_hash: str
    risk_engine_version: str

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        """
        Enforce status and quantity consistency.

        Returns:
            RiskDecision: The validated decision.

        Raises:
            ValueError: If status and quantities disagree.
        """
        if self.status == RiskStatus.REJECTED:
            if self.approved_quantity != 0 or not self.reason_codes:
                raise ValueError("rejected decisions need quantity 0 and reason codes")
        elif self.approved_quantity <= 0:
            raise ValueError("approved or modified decisions need quantity > 0")
        if self.status == RiskStatus.MODIFIED and self.binding_constraint is None:
            raise ValueError("modified decisions need a binding_constraint")
        return self
