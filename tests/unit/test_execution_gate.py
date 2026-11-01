"""T-24: execution gate rejects oversized, missing, or mismatched risk decisions."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from tests.factories import decision, make_ctx, market_intent
from trader.domain.enums import OrderPurpose, ReasonCode, Side
from trader.execution.gate import ExecutionGate, GateContext
from trader.execution.service import ExecutionService
from trader.risk.engine import RiskEngine


def _approved():  # type: ignore[no-untyped-def]
    ctx = make_ctx()
    eng = RiskEngine()
    rd = eng.evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    intent = eng.build_order_intent(rd, ctx)
    assert intent is not None
    return ctx, rd, intent


def _gctx(t, **kw):  # type: ignore[no-untyped-def]
    return GateContext(
        kill_switch_engaged=kw.get("ks", False),
        execution_enabled=kw.get("ex", True),
        now=t,
        adapter_id=kw.get("adapter", "simulated"),
        used_idempotency_keys=kw.get("keys", set()),
    )


def test_valid_intent_passes() -> None:
    """Expected: an intent built from an approved decision passes every check."""
    ctx, rd, intent = _approved()
    assert ExecutionGate().check(intent, rd, _gctx(ctx.decision_time)) == []


def test_t24_excessive_size_missing_and_mismatch() -> None:
    """T-24: +1 step, no decision, other instrument; the adapter is never called."""
    ctx, rd, intent = _approved()
    adapter = MagicMock()
    svc = ExecutionService(adapter)
    bigger = intent.model_copy(update={"quantity": rd.approved_quantity + Decimal("0.00000001")})
    other = intent.model_copy(update={"instrument_id": "ETH-USD"})
    cases = [
        (bigger, rd, ReasonCode.EXCESSIVE_SIZE),
        (intent, None, ReasonCode.RISK_DECISION_MISSING),
        (other, rd, ReasonCode.RISK_DECISION_MISMATCH),
    ]
    for i, r, code in cases:
        res = svc.submit(i, r, _gctx(ctx.decision_time))
        assert code in res.rejected and res.report is None
    adapter.submit_order.assert_not_called()


def test_notional_and_side_checks() -> None:
    """Edge: notional above approval is excessive; a sell against an entry mismatches."""
    ctx, rd, intent = _approved()
    g = ExecutionGate()
    hi = intent.model_copy(update={"notional_estimate_usd": rd.approved_notional_usd + 1})
    assert ReasonCode.EXCESSIVE_SIZE in g.check(hi, rd, _gctx(ctx.decision_time))
    sell = market_intent("BTC-USD", ctx.decision_time, Side.SELL, rd_id=rd.risk_decision_id)
    assert ReasonCode.RISK_DECISION_MISMATCH in g.check(sell, rd, _gctx(ctx.decision_time))


def test_rejected_decision_counts_as_missing() -> None:
    """Failure: an intent pointing at a rejected decision is refused."""
    ctx, rd, intent = _approved()
    rej = rd.model_copy(update={"status": "rejected"})
    assert ReasonCode.RISK_DECISION_MISSING in ExecutionGate().check(
        intent, rej, _gctx(ctx.decision_time)
    )


def test_eg02_to_eg05() -> None:
    """EG-02 kill switch/disabled; EG-03 duplicate key; EG-04 adapter; EG-05 expiry."""
    ctx, rd, intent = _approved()
    g, t = ExecutionGate(), ctx.decision_time
    assert ReasonCode.KILL_SWITCH_ENGAGED in g.check(intent, rd, _gctx(t, ks=True))
    assert ReasonCode.EXECUTION_DISABLED in g.check(intent, rd, _gctx(t, ex=False))
    assert ReasonCode.DUPLICATE_ORDER in g.check(
        intent, rd, _gctx(t, keys={intent.idempotency_key})
    )
    assert ReasonCode.ADAPTER_NOT_ALLOWED in g.check(intent, rd, _gctx(t, adapter="binance"))
    late = intent.valid_until_utc + (intent.valid_until_utc - t)
    assert ReasonCode.INTENT_EXPIRED in g.check(intent, rd, _gctx(late))


def test_protective_stop_exempt_from_kill_switch() -> None:
    """EG-02 exemption: protective stops of filled entries pass with the switch engaged."""
    ctx, rd, intent = _approved()
    stop = intent.model_copy(
        update={
            "purpose": OrderPurpose.PROTECTIVE_STOP,
            "side": Side.SELL,
            "order_type": "stop_market",
            "stop_price": Decimal(95),
            "parent_order_intent_id": intent.order_intent_id,
            "idempotency_key": "stop-key",
        }
    )
    g = GateContext(
        kill_switch_engaged=True,
        execution_enabled=True,
        now=ctx.decision_time,
        adapter_id="simulated",
        filled_entry_ids={intent.order_intent_id},
    )
    assert ExecutionGate().check(stop, rd, g) == []
    g.filled_entry_ids = set()
    assert ReasonCode.KILL_SWITCH_ENGAGED in ExecutionGate().check(stop, rd, g)
