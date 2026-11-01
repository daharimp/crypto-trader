"""T-34: spot long-only: no buy beyond cash, no sell beyond holdings."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.factories import BASE_COSTS, decision, make_ctx, market_intent, signal
from tests.helpers import T0, candle
from trader.domain.enums import EnsembleAction, ExecutionStatus, ReasonCode, Side
from trader.execution.adapters.simulated import SimulatedExecutionAdapter
from trader.portfolio.ledger import Ledger, SpotConstraintError
from trader.risk.engine import RiskEngine

D = Decimal


def test_t34_buy_beyond_cash_rejected_by_risk() -> None:
    """T-34: no available cash -> SPOT_CONSTRAINT_VIOLATION."""
    base = make_ctx()
    pend = market_intent("ETH-USD", base.decision_time, qty="25", notional="2500")
    ctx = make_ctx(pending=[pend])
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert rd.reason_codes == [ReasonCode.SPOT_CONSTRAINT_VIOLATION]


def test_t34_sell_without_holdings_rejected_by_risk() -> None:
    """T-34: exit with nothing held -> SPOT_CONSTRAINT_VIOLATION."""
    base = make_ctx()
    t = base.decision_time
    ctx = make_ctx(signals=[signal("BTC-USD", t, Side.SELL)])
    rd = RiskEngine().evaluate(decision("BTC-USD", t, EnsembleAction.EXIT_LONG), ctx)
    assert rd.reason_codes == [ReasonCode.SPOT_CONSTRAINT_VIOLATION]


def test_t34_adapter_and_ledger_never_negative() -> None:
    """T-34: the simulator refuses oversize fills; the ledger raises instead of going negative."""
    ad = SimulatedExecutionAdapter(D(100), BASE_COSTS)
    buy = market_intent("BTC-USD", T0, Side.BUY, qty="5")  # 500 USD > 100 cash
    ad.submit_order(buy)
    bar = candle(T0, "100", "101", "99", "100")
    [(_, rep)] = ad.fill_market_orders({"BTC-USD": bar}, T0)
    assert rep.status == ExecutionStatus.REJECTED
    assert rep.reason_code == ReasonCode.SPOT_CONSTRAINT_VIOLATION
    assert ad.cash == D(100) and not ad.holdings
    sell = market_intent("BTC-USD", T0, Side.SELL, qty="1", oid="ord-2", key="k2")
    ad.submit_order(sell)
    [(_, rep2)] = ad.fill_market_orders({"BTC-USD": bar}, T0)
    assert rep2.status == ExecutionStatus.REJECTED
    led = Ledger(cash=D(100))
    fake = rep.model_copy(
        update={
            "status": ExecutionStatus.FILLED,
            "filled_quantity": D(5),
            "average_fill_price": D(100),
        }
    )
    with pytest.raises(SpotConstraintError):
        led.apply_fill(buy, fake, "core")
    with pytest.raises(SpotConstraintError):
        led.apply_fill(sell, fake.model_copy(update={"filled_quantity": D(1)}), "core")
    assert led.cash == D(100) and not led.positions
