"""T-30, T-31, T-32: disabled execution states (D-47 disabled execution)."""

from __future__ import annotations

from decimal import Decimal

from tests.factories import decision, flat_candles, make_ctx, make_state, signal
from trader.domain.enums import EnsembleAction, ReasonCode, Side
from trader.execution.gate import ExecutionGate, GateContext
from trader.journal.store import read_events
from trader.pipeline.cycle import run_cycle
from trader.risk.controls import RunControls
from trader.risk.engine import RiskEngine


def test_t30_kill_switch_rejects_entries_and_exits() -> None:
    """T-30: engaged run kill switch -> RR-03 for entries and exits; EG-02 for old intents."""
    eng = RiskEngine()
    pre = make_ctx()
    rd = eng.evaluate(decision("BTC-USD", pre.decision_time), pre)
    intent = eng.build_order_intent(rd, pre)
    assert intent is not None
    ctl = RunControls()
    ctl.kill_switch.engage("test", "manual")
    ctx = make_ctx(controls=ctl)
    assert eng.evaluate(decision("BTC-USD", ctx.decision_time), ctx).reason_codes == [
        ReasonCode.KILL_SWITCH_ENGAGED
    ]
    t = ctx.decision_time
    ex = make_ctx(
        controls=ctl,
        holdings={"BTC-USD": (Decimal(1), Decimal(100))},
        signals=[signal("BTC-USD", t, Side.SELL)],
    )
    assert eng.evaluate(decision("BTC-USD", t, EnsembleAction.EXIT_LONG), ex).reason_codes == [
        ReasonCode.KILL_SWITCH_ENGAGED
    ]
    g = GateContext(kill_switch_engaged=True, execution_enabled=True, now=t, adapter_id="simulated")
    assert ReasonCode.KILL_SWITCH_ENGAGED in ExecutionGate().check(intent, rd, g)


def test_t31_suspended_profile_mid_run() -> None:
    """T-31: profile suspended mid-run (fixture) -> PROFILE_NOT_RUNNABLE, no orders."""
    ctx = make_ctx(profile_update={"status": "suspended"})
    eng = RiskEngine()
    rd = eng.evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert rd.reason_codes == [ReasonCode.PROFILE_NOT_RUNNABLE]
    assert eng.build_order_intent(rd, ctx) is None
    assert all(r.outcome.value == "not_evaluated" for r in rd.rule_results[1:12])


def test_t32_observe_only_and_execution_disabled() -> None:
    """T-32: observe_only and execution disabled -> EXECUTION_DISABLED."""
    from tests.factories import fixture_bundle

    b = fixture_bundle()
    assert b.profile is not None
    obs = b.profile.execution.model_copy(update={"autonomy_mode": "observe_only"})
    ctx = make_ctx(profile_update={"execution": obs})
    assert RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx).reason_codes == [
        ReasonCode.EXECUTION_DISABLED
    ]
    ctl = RunControls(execution_enabled=False)
    ctx2 = make_ctx(controls=ctl)
    assert RiskEngine().evaluate(decision("BTC-USD", ctx2.decision_time), ctx2).reason_codes == [
        ReasonCode.EXECUTION_DISABLED
    ]


def test_t32_cycle_journals_decisions_but_no_intents() -> None:
    """T-32: with execution disabled, signals and decisions are journaled; zero intents."""
    closes = [100] * 50 + [90] * 10 + [130] * 12
    from tests.helpers import series

    c = series(closes)
    c_eth = flat_candles(n=len(c))
    state = make_state({"BTC-USD": c, "ETH-USD": c_eth}, run_id="run-t32")
    # Make BTC eligible: fixture needs 30 days of history; 72 bars = 12 days, so relax via
    # a universe-independent check -> the decision is rejected before RR-05 anyway.
    state.controls.execution_enabled = False
    for bar in c[50:]:
        run_cycle(state, bar.close_time_utc)
    events = read_events("run-t32")
    types = [e["event_type"] for e in events]
    assert "SIGNAL_GENERATED" in types and "RISK_EVALUATED" in types
    assert "ORDER_INTENT_CREATED" not in types
    risk = [e["payload"] for e in events if e["event_type"] == "RISK_EVALUATED"]
    assert all(r["reason_codes"] == ["EXECUTION_DISABLED"] for r in risk)
