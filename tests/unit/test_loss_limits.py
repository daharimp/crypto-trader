"""T-27, T-28, T-29: daily loss limit, circuit breaker, loss scaling (D-47 loss limits)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.factories import decision, flat_candles, make_ctx, params_with, signal
from trader.domain.enums import EnsembleAction, EventType, ReasonCode, RiskStatus, Side
from trader.risk.controls import CircuitBreaker, KillSwitchError, RunControls
from trader.risk.engine import RiskEngine
from trader.risk.loss_state import LossTracker, loss_multiplier

D = Decimal


def _tracker(start: str, now: str, hwm: str | None = None) -> LossTracker:
    lt = LossTracker(D(start))
    if hwm:
        lt.hwm = D(hwm)
    lt.equity = D(now)
    return lt


def test_t27_daily_loss_blocks_entries_until_midnight() -> None:
    """T-27: down 3.1% since 00:00 UTC -> DAILY_LOSS_LIMIT until next midnight; exits ok."""
    ctl = RunControls()
    c = flat_candles()
    t = c[-1].close_time_utc
    lt = _tracker("2500", "2422.50")  # -3.1%
    eng = RiskEngine()
    ctx = make_ctx(candles=c, cash=D("2422.50"), loss=lt, controls=ctl)
    rd = eng.evaluate(decision("BTC-USD", t), ctx)
    assert rd.reason_codes == [ReasonCode.DAILY_LOSS_LIMIT]
    assert ctl.lockout.until is not None and ctl.lockout.until.hour == 0
    assert any(e[0] == EventType.DAILY_LOCKOUT_STARTED for e in ctl.events)
    # Still locked later that day even after equity recovers.
    later = c[: len(c) - 1]
    ctx2 = make_ctx(candles=later, cash=D(2500), controls=ctl)
    assert ctl.lockout.active(ctx2.decision_time)
    # Exits are allowed.
    ex = make_ctx(
        candles=c,
        cash=D("2322.50"),
        holdings={"BTC-USD": (D(1), D(100))},
        loss=lt,
        controls=ctl,
        signals=[signal("BTC-USD", t, Side.SELL)],
    )
    rd_exit = eng.evaluate(decision("BTC-USD", t, EnsembleAction.EXIT_LONG), ex)
    assert rd_exit.status == RiskStatus.APPROVED and rd_exit.approved_quantity == 1
    # After midnight the lockout ends.
    assert not ctl.lockout.active(ctl.lockout.until)


def test_daily_loss_below_limit_passes() -> None:
    """Edge: 2.9% loss passes RR-10."""
    rd = RiskEngine().evaluate(
        decision("BTC-USD", flat_candles()[-1].close_time_utc),
        make_ctx(cash=D("2427.50"), loss=_tracker("2500", "2427.50")),
    )
    assert ReasonCode.DAILY_LOSS_LIMIT not in rd.reason_codes


def test_t28_breaker_latches() -> None:
    """T-28: 15% drawdown opens once; later entries rejected even after recovery."""
    ctl = RunControls()
    eng = RiskEngine()
    lt = _tracker("2125", "2125", hwm="2500")  # 15% drawdown, day start = equity
    lt.day_start = D(2125)
    ctx = make_ctx(cash=D(2125), loss=lt, controls=ctl)
    rd = eng.evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert rd.reason_codes == [ReasonCode.CIRCUIT_BREAKER_OPEN]
    opened = [e for e in ctl.drain() if e[0] == EventType.CIRCUIT_BREAKER_OPENED]
    assert len(opened) == 1
    rec = make_ctx(cash=D(2500), controls=ctl)  # recovered
    rd2 = eng.evaluate(decision("BTC-USD", rec.decision_time), rec)
    assert rd2.reason_codes == [ReasonCode.CIRCUIT_BREAKER_OPEN]
    assert not [e for e in ctl.drain() if e[0] == EventType.CIRCUIT_BREAKER_OPENED]
    t = rec.decision_time
    ex = make_ctx(
        cash=D(2000),
        holdings={"BTC-USD": (D(1), D(100))},
        controls=ctl,
        signals=[signal("BTC-USD", t, Side.SELL)],
    )
    assert eng.evaluate(decision("BTC-USD", t, EnsembleAction.EXIT_LONG), ex).status == "approved"


def test_breaker_reset_requires_owner() -> None:
    """Failure: automation cannot reset the breaker."""
    b = CircuitBreaker()
    b.trip(flat_candles()[-1].close_time_utc)
    with pytest.raises(KillSwitchError):
        b.reset("auto")
    b.reset("owner reviewed", by_owner=True)
    assert not b.open


@pytest.mark.parametrize(("frac", "mult"), [("0.2", "1.0"), ("0.5", "0.5"), ("0.8", "0.25")])
def test_t29_loss_scaling(frac: str, mult: str) -> None:
    """T-29: drawdowns at 0.2, 0.5, 0.8 of breaker -> multipliers 1.0, 0.5, 0.25."""
    p = params_with()
    dd = p.breaker_pct * D(frac)
    assert loss_multiplier(p, dd) == D(mult)
    hwm = D(2500)
    eq = hwm * (1 - dd / 100)
    lt = _tracker(str(eq), str(eq), hwm=str(hwm))
    ctx = make_ctx(cash=eq, loss=lt)
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    full = make_ctx(cash=eq)
    rd_full = RiskEngine().evaluate(decision("BTC-USD", full.decision_time), full)
    assert rd.approved_notional_usd <= rd_full.approved_notional_usd * D(mult) + D("0.01")
    assert rd.approved_notional_usd >= rd_full.approved_notional_usd * D(mult) - D("0.01")


def test_linear_schedule_and_beyond_breaker() -> None:
    """Edge: linear method and multiplier 0 at the breaker."""
    p = params_with(schedule_method="linear_to_breaker")
    assert loss_multiplier(p, p.breaker_pct / 2) == D("0.5")
    assert loss_multiplier(params_with(), params_with().breaker_pct) == 0
    _ = timedelta
