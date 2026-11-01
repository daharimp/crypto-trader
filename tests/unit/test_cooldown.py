"""T-33: cooldown after consecutive losses."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from tests.factories import decision, make_ctx
from trader.domain.enums import ReasonCode
from trader.risk.controls import Cooldowns, RunControls
from trader.risk.engine import RiskEngine

D = Decimal


def test_t33_three_losses_start_24h_cooldown() -> None:
    """T-33: 3 losing trades -> cooldown 24 h -> COOLDOWN_ACTIVE, then allowed."""
    ctl = RunControls()
    base = make_ctx()
    t = base.decision_time
    key = Cooldowns.key("sma_trend", "BTC-USD")
    assert ctl.cooldowns.record_exit(key, D(-1), t - timedelta(hours=8), 3, D(24)) is None
    assert ctl.cooldowns.record_exit(key, D(-1), t - timedelta(hours=4), 3, D(24)) is None
    until = ctl.cooldowns.record_exit(key, D(-1), t, 3, D(24))
    assert until == t + timedelta(hours=24)
    eng = RiskEngine()
    ctx = make_ctx(controls=ctl)
    assert eng.evaluate(decision("BTC-USD", t), ctx).reason_codes == [ReasonCode.COOLDOWN_ACTIVE]
    assert ctl.cooldowns.active(key, t + timedelta(hours=23))
    assert not ctl.cooldowns.active(key, t + timedelta(hours=24))


def test_win_resets_count() -> None:
    """Edge: a winning trade resets the consecutive-loss count."""
    c = Cooldowns()
    t = make_ctx().decision_time
    c.record_exit("k", D(-1), t, 3, D(24))
    c.record_exit("k", D(-1), t, 3, D(24))
    c.record_exit("k", D(5), t, 3, D(24))
    assert c.record_exit("k", D(-1), t, 3, D(24)) is None
    assert c.losses["k"] == 1


def test_cooldown_is_per_strategy_instrument() -> None:
    """Failure isolation: a BTC cooldown does not block ETH."""
    ctl = RunControls()
    t = make_ctx().decision_time
    for _ in range(3):
        ctl.cooldowns.record_exit(Cooldowns.key("sma_trend", "ETH-USD"), D(-1), t, 3, D(24))
    rd = RiskEngine().evaluate(decision("BTC-USD", t), make_ctx(controls=ctl))
    assert ReasonCode.COOLDOWN_ACTIVE not in rd.reason_codes
