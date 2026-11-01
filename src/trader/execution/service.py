"""Execution service: gate check, then submission to the allowlisted adapter."""

from __future__ import annotations

from dataclasses import dataclass

from trader.domain.enums import ReasonCode
from trader.domain.execution import ExecutionReport
from trader.domain.orders import OrderIntent
from trader.domain.risk import RiskDecision

from .adapters.base import ExecutionAdapter
from .gate import ExecutionGate, GateContext


@dataclass
class SubmitResult:
    """Outcome of a submission attempt."""

    rejected: list[ReasonCode]
    report: ExecutionReport | None


class ExecutionService:
    """Owns the gate and the adapter; the only path to an adapter."""

    def __init__(self, adapter: ExecutionAdapter, gate: ExecutionGate | None = None) -> None:
        """
        Create the service.

        Args:
            adapter (ExecutionAdapter): Simulated adapter.
            gate (ExecutionGate | None): Gate (default instance).
        """
        self.adapter = adapter
        self.gate = gate or ExecutionGate()

    def submit(
        self, intent: OrderIntent, rd: RiskDecision | None, ctx: GateContext
    ) -> SubmitResult:
        """
        Gate-check and submit. Nothing reaches the adapter if any check fails.

        Args:
            intent (OrderIntent): Intent (already journaled).
            rd (RiskDecision | None): Its risk decision.
            ctx (GateContext): Gate state.

        Returns:
            SubmitResult: Rejections or the adapter report.
        """
        reasons = self.gate.check(intent, rd, ctx)
        if reasons:
            return SubmitResult(reasons, None)
        ctx.used_idempotency_keys.add(intent.idempotency_key)
        return SubmitResult([], self.adapter.submit_order(intent))
