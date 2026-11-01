"""T-26: duplicate orders are rejected (D-47 duplicate orders)."""

from __future__ import annotations

from decimal import Decimal

from tests.factories import decision, make_ctx, market_intent
from trader.domain.enums import ReasonCode
from trader.risk.engine import RiskEngine


def test_t26_same_decision_twice() -> None:
    """T-26: the same decision with its key already used -> DUPLICATE_ORDER."""
    ctx = make_ctx()
    eng = RiskEngine()
    rd = eng.evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    intent = eng.build_order_intent(rd, ctx)
    assert intent is not None
    again = make_ctx(used_keys={intent.idempotency_key})
    rd2 = eng.evaluate(decision("BTC-USD", again.decision_time), again)
    assert rd2.reason_codes == [ReasonCode.DUPLICATE_ORDER]


def test_t26_entry_while_market_order_pending() -> None:
    """T-26: a pending (unfilled) market order for the instrument blocks a new entry."""
    base = make_ctx()
    pend = market_intent("BTC-USD", base.decision_time)
    ctx = make_ctx(pending=[pend])
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert rd.reason_codes == [ReasonCode.DUPLICATE_ORDER]


def test_t26_entry_while_long() -> None:
    """T-26: entries only when flat."""
    ctx = make_ctx(holdings={"BTC-USD": (Decimal(1), Decimal(100))})
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert rd.reason_codes == [ReasonCode.DUPLICATE_ORDER]


def test_pending_order_other_instrument_ok() -> None:
    """Edge: a pending order on another instrument does not block."""
    base = make_ctx()
    ctx = make_ctx(pending=[market_intent("ETH-USD", base.decision_time)])
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert not rd.reason_codes
