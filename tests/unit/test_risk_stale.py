"""T-23: stale data is rejected (D-47 stale data)."""

from __future__ import annotations

from datetime import timedelta

from tests.factories import decision, flat_candles, make_ctx
from trader.domain.enums import EnsembleAction, ReasonCode, RiskStatus, Side
from trader.risk.engine import RiskEngine


def test_t23_stale_snapshot_rejected() -> None:
    """T-23: the expected latest candle is missing -> STALE_DATA and no intent."""
    c = flat_candles()
    t = c[-1].close_time_utc + timedelta(hours=4)  # bar closing at t is missing
    ctx = make_ctx(candles=c, t=t)
    assert not ctx.snapshot.is_fresh
    eng = RiskEngine()
    rd = eng.evaluate(decision("BTC-USD", t), ctx)
    assert rd.status == RiskStatus.REJECTED and rd.reason_codes == [ReasonCode.STALE_DATA]
    assert eng.build_order_intent(rd, ctx) is None


def test_stale_blocks_exits_too() -> None:
    """Edge: exits also need fresh data (RR-06 applies to exits)."""
    c = flat_candles()
    t = c[-1].close_time_utc + timedelta(hours=4)
    ctx = make_ctx(
        candles=c,
        t=t,
        holdings={
            "BTC-USD": (__import__("decimal").Decimal(1), __import__("decimal").Decimal(100))
        },
        signals=[
            __import__("tests.factories", fromlist=["signal"]).signal("BTC-USD", t, Side.SELL)
        ],
    )
    rd = RiskEngine().evaluate(decision("BTC-USD", t, EnsembleAction.EXIT_LONG), ctx)
    assert rd.reason_codes == [ReasonCode.STALE_DATA]


def test_fresh_snapshot_passes_rr06() -> None:
    """Expected: a fresh snapshot passes RR-06."""
    ctx = make_ctx()
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert next(r for r in rd.rule_results if r.rule_id == "RR-06").outcome.value == "pass"
