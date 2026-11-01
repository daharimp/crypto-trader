"""Edge and failure branches of the risk engine (coverage target: trader.risk >= 95%)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.factories import (
    decision,
    eligible_universe,
    fixture_bundle,
    make_ctx,
    market_intent,
    params_with,
    signal,
)
from trader.domain.enums import EnsembleAction, Environment, ReasonCode, RiskStatus, Sleeve
from trader.domain.universe import AssetRegistry
from trader.risk.controls import CircuitBreaker, KillSwitchError, PersistedKillSwitch
from trader.risk.engine import RiskEngine
from trader.risk.loss_state import LossTracker
from trader.risk.params import StopPolicyParams, risk_params_from_compiled
from trader.risk.rules import rr02_config_resolved, rr04_safety
from trader.universe.registry import Registry

D = Decimal


def _rd(**kw):  # type: ignore[no-untyped-def]
    ctx = make_ctx(**kw)
    return RiskEngine().evaluate(decision(ctx.snapshot.instrument_id, ctx.decision_time), ctx)


@pytest.mark.parametrize(
    "stop",
    [
        StopPolicyParams("atr_multiple", 20, D(2), None),  # period unsupported by features
        StopPolicyParams("atr_multiple", 14, None, None),  # multiple missing
        StopPolicyParams("unknown", None, None, None),
        StopPolicyParams("atr_multiple", 14, D(100), None),  # distance >= 100%
    ],
)
def test_stop_inputs_invalid(stop: StopPolicyParams) -> None:
    """RR-14: unusable stop inputs reject with RISK_CONFIG_UNRESOLVED."""
    rd = _rd(params=params_with(stop=stop))
    assert rd.reason_codes == [ReasonCode.RISK_CONFIG_UNRESOLVED]


def test_fixed_pct_stop() -> None:
    """RR-14: fixed_pct stop distance."""
    rd = _rd(params=params_with(stop=StopPolicyParams("fixed_pct", None, None, D(5))))
    assert rd.status == RiskStatus.APPROVED and rd.stop is not None
    assert rd.stop.stop_distance_pct == D(5) and rd.stop.method == "fixed_pct"


def test_missing_tier_cap() -> None:
    """RR-15: a tier with no cap rejects (never defaults)."""
    rd = _rd(params=params_with(tier_caps={}))
    assert rd.reason_codes == [ReasonCode.RISK_CONFIG_UNRESOLVED]


def _spec_ctx(spec_total: Decimal | None, **kw):  # type: ignore[no-untyped-def]
    data = fixture_bundle().registry
    assert data is not None
    raw = data.model_dump()
    raw["assets"].append(
        {
            "asset_id": "PEPE",
            "name": "p",
            "tier": "speculative",
            "tier_status": "approved",
            "aliases": [],
            "blocked": False,
        }
    )
    raw["instruments"].append(
        {
            "instrument_id": "PEPE-USD",
            "base": "PEPE",
            "quote": "USD",
            "type": "spot",
            "quantity_step": "1",
        }
    )
    reg = Registry(AssetRegistry.model_validate(raw))
    prof = fixture_bundle().profile
    assert prof is not None
    uni = prof.universe.model_copy(update={"instruments_in_scope": ["BTC-USD", "PEPE-USD"]})
    base = make_ctx(inst="PEPE-USD")
    p = params_with(
        speculative_total_pct=spec_total, tier_caps={"core": D(35), "speculative": D(5)}
    )
    return make_ctx(
        inst="PEPE-USD",
        registry=reg,
        profile_update={"universe": uni},
        params=p,
        universe=eligible_universe(base.decision_time, ["PEPE-USD"]),
        **kw,
    )


def test_speculative_caps() -> None:
    """RR-15/RR-16: speculative tier uses its per-asset and total caps."""
    ctx = _spec_ctx(D(10))
    rd = RiskEngine().evaluate(decision("PEPE-USD", ctx.decision_time), ctx)
    assert rd.status == RiskStatus.MODIFIED and rd.binding_constraint.value == "TIER_CAP"
    assert rd.approved_notional_usd <= D(125)
    assert next(r for r in rd.rule_results if r.rule_id == "RR-16").outcome.value == "pass"
    tight = _spec_ctx(D("4.5"))  # $112.50 < tier cap $125; step 1 still fits one unit
    rd2 = RiskEngine().evaluate(decision("PEPE-USD", tight.decision_time), tight)
    assert rd2.binding_constraint.value == "SPECULATIVE_CAP"


def test_speculative_total_missing() -> None:
    """RR-16: a speculative asset with no total cap is rejected."""
    ctx = _spec_ctx(None)
    rd = RiskEngine().evaluate(decision("PEPE-USD", ctx.decision_time), ctx)
    assert rd.reason_codes == [ReasonCode.RISK_CONFIG_UNRESOLVED]


def test_max_positions() -> None:
    """RR-19: open positions plus pending entries at the maximum."""
    rd = _rd(params=params_with(max_open_positions=1), holdings={"ETH-USD": (D(1), D(100))})
    assert rd.reason_codes == [ReasonCode.MAX_POSITIONS]
    base = make_ctx()
    rd2 = _rd(
        params=params_with(max_open_positions=1),
        pending=[market_intent("ETH-USD", base.decision_time, qty="0.1")],
    )
    assert rd2.reason_codes == [ReasonCode.MAX_POSITIONS]


def test_size_below_minimum() -> None:
    """RR-20: tiny equity -> SIZE_BELOW_MINIMUM."""
    rd = _rd(cash=D(20))
    assert rd.reason_codes == [ReasonCode.SIZE_BELOW_MINIMUM]


def test_rr01_rr02_unrunnable_and_unresolved() -> None:
    """RR-01 and RR-02 with an unrunnable compile and with missing params."""
    from tests.conftest import PROFILE
    from trader.profiles.compiler import compile_bundle

    blocked = compile_bundle(PROFILE, Environment.BACKTEST).compiled
    rd = _rd(compiled=blocked, params=None)
    assert rd.reason_codes == [ReasonCode.PROFILE_NOT_RUNNABLE]
    rd2 = _rd(params=None)
    assert rd2.reason_codes == [ReasonCode.RISK_CONFIG_UNRESOLVED]
    assert risk_params_from_compiled(blocked) is None


def test_rr02_paper_refuses_experiment_values() -> None:
    """RR-02: in paper, experiment/fixture provenance is refused."""
    ctx = make_ctx(environment=Environment.PAPER)
    r = rr02_config_resolved(ctx, True)
    assert r.reason_code == ReasonCode.RISK_CONFIG_UNRESOLVED and "non_approved" in r.detail
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert rd.reason_codes == [ReasonCode.PROFILE_NOT_RUNNABLE]


def test_rr04_detects_bypassed_constants() -> None:
    """RR-04: defence in depth if a profile was constructed without validation."""
    prof = fixture_bundle().profile
    assert prof is not None
    bad_exec = prof.execution.model_construct(
        **{**prof.execution.__dict__, "leverage_allowed": True}
    )
    ctx = make_ctx(profile_update={"execution": bad_exec})
    assert rr04_safety(ctx, True).reason_code == ReasonCode.SAFETY_VIOLATION


def test_rr12_intraday_signal_rejected() -> None:
    """RR-12: intraday sleeve signals are rejected in M1."""
    base = make_ctx()
    rd = _rd(signals=[signal("BTC-USD", base.decision_time, sleeve=Sleeve.INTRADAY)])
    assert rd.reason_codes == [ReasonCode.INTRADAY_SLEEVE_DISABLED]


def test_engine_refuses_hold_and_bad_stop_inputs() -> None:
    """Failure: hold has no RiskDecision; stops need a fill price."""
    ctx = make_ctx()
    eng = RiskEngine()
    with pytest.raises(ValueError):
        eng.evaluate(
            decision("BTC-USD", ctx.decision_time, EnsembleAction.HOLD).model_copy(
                update={"action": EnsembleAction.HOLD}
            ),
            ctx,
        )
    rd = eng.evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    intent = eng.build_order_intent(rd, ctx)
    assert intent is not None
    from tests.factories import BASE_COSTS
    from trader.execution.adapters.simulated import SimulatedExecutionAdapter

    rep = SimulatedExecutionAdapter(D(5000), BASE_COSTS).submit_order(intent)
    with pytest.raises(ValueError):
        eng.build_protective_stop_intent(intent, rep, rd, ctx)


def test_controls_edges() -> None:
    """Controls: double trip, persisted switch helpers, blank reasons, zero day start."""
    b = CircuitBreaker()
    now = datetime(2024, 1, 1, tzinfo=UTC)
    assert b.trip(now) and not b.trip(now)
    ks = PersistedKillSwitch()
    assert not ks.is_engaged()
    ks.engage("auto", now, trigger="clock_skew_exceeded")
    assert ks.is_engaged() and ks.state().changed_by == "system"  # type: ignore[union-attr]
    with pytest.raises(KillSwitchError):
        ks.engage(" ", now)
    lt = LossTracker(D(0))
    assert lt.daily_pnl_pct == 0 and lt.drawdown_pct == 0
    assert lt.state(None, False, False).loss_scaling_multiplier == 0
    _ = replace
