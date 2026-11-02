"""RiskEngine (§7.8): every proposal passes RR-01 to RR-20; nothing bypasses it."""

from __future__ import annotations

from decimal import Decimal

from trader.common.clock import timeframe_delta
from trader.domain.common import VersionRef
from trader.domain.ensemble import EnsembleDecision
from trader.domain.enums import (
    EnsembleAction,
    Environment,
    OrderPurpose,
    OrderType,
    ReasonCode,
    RiskStatus,
    RuleOutcome,
    Side,
)
from trader.domain.execution import ExecutionReport
from trader.domain.orders import OrderIntent
from trader.domain.risk import RiskDecision, RuleResult

from .context import RiskContext
from .intents import idempotency_key
from .rules import GATE_RULES, result
from .sizing import size_entry


class RiskEngine:
    """Deterministic risk evaluation, sizing, and order-intent construction."""

    version = "1.0.0"

    def evaluate(self, decision: EnsembleDecision, ctx: RiskContext) -> RiskDecision:
        """
        Evaluate an ``enter_long`` or ``exit_long`` decision.

        Args:
            decision (EnsembleDecision): Ensemble decision.
            ctx (RiskContext): Context.

        Returns:
            RiskDecision: Approved, modified, or rejected decision with all rule results.

        Raises:
            ValueError: For ``hold`` or ``no_trade`` (they produce no RiskDecision).
        """
        if decision.action not in (EnsembleAction.ENTER_LONG, EnsembleAction.EXIT_LONG):
            raise ValueError("only enter_long and exit_long are risk-evaluated")
        entry = decision.action == EnsembleAction.ENTER_LONG
        rules: list[RuleResult] = []
        failed: ReasonCode | None = None
        for rule_id, fn, for_exits in GATE_RULES:
            if not entry and not for_exits:
                rules.append(result(rule_id, RuleOutcome.NOT_APPLICABLE))
            elif failed is not None:
                rules.append(result(rule_id, RuleOutcome.NOT_EVALUATED))
            else:
                r = fn(ctx, entry)
                rules.append(r)
                if r.outcome == RuleOutcome.FAIL:
                    failed = r.reason_code
        qty = notional = Decimal(0)
        stop = binding = None
        price = ctx.snapshot.latest_bar.close if ctx.snapshot.latest_bar else Decimal(0)
        if entry:
            if failed is None:
                sz = size_entry(ctx)
                rules.extend(sz.rules)
                failed, qty, notional, stop, binding = (
                    sz.rejected,
                    sz.quantity,
                    sz.notional,
                    sz.stop,
                    sz.binding,
                )
            else:
                rules.extend(result(f"RR-{n}", RuleOutcome.NOT_EVALUATED) for n in range(13, 21))
        else:
            rules.extend(result(f"RR-{n}", RuleOutcome.NOT_APPLICABLE) for n in range(13, 21))
            if failed is None:
                qty = ctx.held_quantity(ctx.snapshot.instrument_id)
                notional = qty * price * (1 - ctx.costs.slippage)
        if failed is not None:
            status, qty, notional, binding = RiskStatus.REJECTED, Decimal(0), Decimal(0), None
        else:
            status = RiskStatus.APPROVED if binding is None else RiskStatus.MODIFIED
        loss = ctx.loss.model_copy(
            update={
                "breaker_open": ctx.controls.breaker.open,
                "daily_lockout_active": ctx.controls.lockout.active(ctx.decision_time),
            }
        )
        return RiskDecision(
            schema_version="1.0.0",
            risk_decision_id=ctx.ids.next("rsk"),
            correlation_id=decision.correlation_id,
            cycle_id=decision.cycle_id,
            ensemble_decision_id=decision.ensemble_decision_id,
            instrument_id=decision.instrument_id,
            decision_time_utc=decision.decision_time_utc,
            action_evaluated="enter_long" if entry else "exit_long",
            status=status,
            approved_quantity=qty,
            approved_notional_usd=notional,
            reference_price=price,
            stop=stop,
            loss_state=loss,
            rule_results=rules,
            reason_codes=[failed] if failed else [],
            binding_constraint=binding,
            config_hash=ctx.compiled.config_hash,
            risk_engine_version=self.version,
        )

    def build_order_intent(self, rd: RiskDecision, ctx: RiskContext) -> OrderIntent | None:
        """
        Build the market order intent for an approved or modified decision.

        Args:
            rd (RiskDecision): Risk decision.
            ctx (RiskContext): Context.

        Returns:
            OrderIntent | None: Intent, or None if the decision was rejected.
        """
        if rd.status == RiskStatus.REJECTED:
            return None
        entry = rd.action_evaluated == "enter_long"
        side, purpose = (Side.BUY, OrderPurpose.ENTRY) if entry else (Side.SELL, OrderPurpose.EXIT)
        t = rd.decision_time_utc
        latest = ctx.snapshot.latest_bar
        assert latest is not None
        return OrderIntent(
            schema_version="1.0.0",
            order_intent_id=ctx.ids.next("ord"),
            correlation_id=rd.correlation_id,
            cycle_id=rd.cycle_id,
            idempotency_key=idempotency_key(
                ctx.compiled.config_hash, rd.instrument_id, side, purpose, t
            ),
            risk_decision_id=rd.risk_decision_id,
            ensemble_decision_id=rd.ensemble_decision_id,
            signal_ids=[s.signal_id for s in ctx.signals],
            strategy_versions=[
                VersionRef(id=s.strategy_id, version=s.strategy_version) for s in ctx.signals
            ],
            model_versions=[
                VersionRef(id=s.model_id, version=s.model_version or "")
                for s in ctx.signals
                if s.model_id
            ],
            instrument_id=rd.instrument_id,
            side=side,
            purpose=purpose,
            order_type=OrderType.MARKET,
            quantity=rd.approved_quantity,
            reference_price=rd.reference_price,
            stop_price=None,
            attached_stop_distance_pct=rd.stop.stop_distance_pct if entry and rd.stop else None,
            parent_order_intent_id=None,
            notional_estimate_usd=rd.approved_notional_usd,
            valid_until_utc=t + timeframe_delta(ctx.timeframe),
            environment=ctx.environment,
            funds="real" if ctx.environment == Environment.LIVE else "simulated",
            config_hash=ctx.compiled.config_hash,
            market_data_timestamp_utc=latest.close_time_utc,
            decision_time_utc=t,
            created_at_utc=t,
        )

    def build_protective_stop_intent(
        self, entry: OrderIntent, fill: ExecutionReport, rd: RiskDecision, ctx: RiskContext
    ) -> OrderIntent:
        """
        Build the resting protective stop for a filled entry.

        Args:
            entry (OrderIntent): Filled entry intent.
            fill (ExecutionReport): Entry fill.
            rd (RiskDecision): The entry's risk decision.
            ctx (RiskContext): Context (for IDs and timeframe).

        Returns:
            OrderIntent: ``protective_stop`` / ``stop_market`` intent.

        Raises:
            ValueError: If the entry has no fill price or stop distance.
        """
        if fill.average_fill_price is None or entry.attached_stop_distance_pct is None:
            raise ValueError("protective stop needs a fill price and stop distance")
        stop_d = entry.attached_stop_distance_pct / Decimal(100)
        stop_price = fill.average_fill_price * (1 - stop_d)
        filled_at = fill.filled_at_utc or entry.decision_time_utc
        # Reason: model_validate (not model_copy) so OrderIntent validators run on the stop.
        return OrderIntent.model_validate(
            entry.model_dump()
            | {
                "order_intent_id": ctx.ids.next("ord"),
                "idempotency_key": idempotency_key(
                    entry.config_hash,
                    entry.instrument_id,
                    Side.SELL,
                    OrderPurpose.PROTECTIVE_STOP,
                    entry.decision_time_utc,
                ),
                "side": Side.SELL,
                "purpose": OrderPurpose.PROTECTIVE_STOP,
                "order_type": OrderType.STOP_MARKET,
                "quantity": fill.filled_quantity,
                "reference_price": stop_price,
                "stop_price": stop_price,
                "attached_stop_distance_pct": None,
                "parent_order_intent_id": entry.order_intent_id,
                "notional_estimate_usd": fill.filled_quantity * stop_price,
                # Reason: stops rest until filled or canceled; valid_until only bounds the
                # submission check (EG-05), which happens at the entry fill time.
                "valid_until_utc": filled_at + timeframe_delta(ctx.timeframe),
                "created_at_utc": filled_at,
            }
        )
