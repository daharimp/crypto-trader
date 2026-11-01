"""Execution gate EG-01 to EG-05 (architecture.md §6.9). Last check before the adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from trader.domain.enums import OrderPurpose, ReasonCode, RiskStatus, Side
from trader.domain.orders import OrderIntent
from trader.domain.risk import RiskDecision

from .adapters.registry import ALLOWED_ADAPTERS

R = ReasonCode


@dataclass
class GateContext:
    """State the gate reads."""

    kill_switch_engaged: bool
    execution_enabled: bool
    now: datetime
    adapter_id: str
    used_idempotency_keys: set[str] = field(default_factory=set)
    filled_entry_ids: set[str] = field(default_factory=set)


class ExecutionGate:
    """Rejects any intent that is not exactly backed by an approved RiskDecision."""

    def check(
        self, intent: OrderIntent, rd: RiskDecision | None, ctx: GateContext
    ) -> list[ReasonCode]:
        """
        Run EG-01 to EG-05.

        Args:
            intent (OrderIntent): Intent to submit.
            rd (RiskDecision | None): The decision it claims to come from.
            ctx (GateContext): Gate state.

        Returns:
            list[ReasonCode]: Failures (empty means the intent may be submitted).
        """
        out: list[ReasonCode] = []
        # EG-01 risk decision present, approved, matching, and not exceeded
        if rd is None or rd.risk_decision_id != intent.risk_decision_id:
            out.append(R.RISK_DECISION_MISSING)
        elif rd.status == RiskStatus.REJECTED:
            out.append(R.RISK_DECISION_MISSING)
        else:
            if intent.purpose == OrderPurpose.PROTECTIVE_STOP:
                expected_side, expected_action = Side.SELL, "enter_long"
            else:
                expected_side = Side.BUY if rd.action_evaluated == "enter_long" else Side.SELL
                expected_action = rd.action_evaluated
            if (
                rd.instrument_id != intent.instrument_id
                or intent.side != expected_side
                or rd.action_evaluated != expected_action
            ):
                out.append(R.RISK_DECISION_MISMATCH)
            elif intent.quantity > rd.approved_quantity or (
                intent.purpose != OrderPurpose.PROTECTIVE_STOP
                and intent.notional_estimate_usd > rd.approved_notional_usd
            ):
                out.append(R.EXCESSIVE_SIZE)
        # EG-02 kill switch / execution flag (protective stops of filled entries exempt)
        exempt = (
            intent.purpose == OrderPurpose.PROTECTIVE_STOP
            and intent.parent_order_intent_id in ctx.filled_entry_ids
        )
        if not exempt:
            if ctx.kill_switch_engaged:
                out.append(R.KILL_SWITCH_ENGAGED)
            elif not ctx.execution_enabled:
                out.append(R.EXECUTION_DISABLED)
        # EG-03 idempotency
        if intent.idempotency_key in ctx.used_idempotency_keys:
            out.append(R.DUPLICATE_ORDER)
        # EG-04 simulated funds and allowlisted adapter
        if intent.funds != "simulated" or ctx.adapter_id not in ALLOWED_ADAPTERS:
            out.append(R.ADAPTER_NOT_ALLOWED)
        # EG-05 not expired
        if ctx.now > intent.valid_until_utc:
            out.append(R.INTENT_EXPIRED)
        return out
