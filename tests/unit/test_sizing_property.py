"""T-25: approved size never exceeds any cap; quantities round down (D-47 excessive sizing)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.factories import BASE_COSTS, decision, make_ctx, params_with, series
from trader.domain.enums import RiskStatus
from trader.execution.costs import CostParams
from trader.risk.engine import RiskEngine

STEP = Decimal("0.00000001")
D = Decimal


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    cash=st.integers(100, 100_000),
    held_qty=st.integers(0, 50),
    price=st.integers(5, 5000),
    spread=st.integers(1, 40),
    rpt=st.sampled_from(["0.25", "0.5", "1", "2"]),
    cap=st.integers(5, 60),
    total=st.integers(10, 90),
    reserve=st.integers(0, 40),
    atr_mult=st.sampled_from(["1", "2", "3.5"]),
    fee=st.sampled_from(["0.1", "0.4", "0.6"]),
    slip=st.sampled_from(["5", "10", "25"]),
)
def test_t25_size_within_every_cap(
    cash: int,
    held_qty: int,
    price: int,
    spread: int,
    rpt: str,
    cap: int,
    total: int,
    reserve: int,
    atr_mult: str,
    fee: str,
    slip: str,
) -> None:
    """T-25: notional <= each headroom and N_risk; reserve kept; qty is a rounded-down step."""
    p = params_with(
        risk_per_trade_pct=D(rpt),
        tier_caps={"core": D(cap)},
        total_exposure_pct=D(total),
        reserve_low_pct=D(reserve),
        stop=params_with().stop.__class__("atr_multiple", 14, D(atr_mult), None),
    )
    costs = CostParams("x", D(fee), D(slip), D(10))
    closes = [price] * 60
    candles = series(closes)
    # widen ranges so ATR = 2 * spread
    candles = [
        c.model_copy(update={"high": c.close + spread, "low": max(c.close - spread, D(1))})
        for c in candles
    ]
    held = {"ETH-USD": (D(held_qty), D(price))} if held_qty else {}
    ctx = make_ctx(candles=candles, cash=D(cash), params=p, costs=costs, holdings=held)
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    E = ctx.position.equity_usd
    if rd.status == RiskStatus.REJECTED:
        assert rd.approved_quantity == 0
        return
    q, n = rd.approved_quantity, rd.approved_notional_usd
    assert q > 0 and q == (q / STEP).to_integral_value() * STEP
    p_cons = D(price) * (1 + costs.slippage)
    assert n == q * p_cons
    stop_d = rd.stop.stop_distance_pct / 100 if rd.stop else D(0)
    n_risk = E * D(rpt) / 100 * ctx.loss.loss_scaling_multiplier / stop_d
    assert n <= n_risk
    assert n <= E * D(cap) / 100  # BTC held 0
    assert n <= E * D(total) / 100 - ctx.market_value()
    # Reserve floor kept after the order and its fee.
    assert ctx.position.cash_usd - n * (1 + costs.fee_rate) >= E * D(reserve) / 100 - D("1e-9")
    # Rounding down: one more step would exceed the bound or the binding headroom.
    assert (q + STEP) * p_cons > min(
        n_risk,
        E * D(cap) / 100,
        E * D(total) / 100 - ctx.market_value(),
        (ctx.position.cash_usd - E * D(reserve) / 100) / (1 + costs.fee_rate),
    ) - D("1e-9")


def test_modified_when_cap_binds() -> None:
    """Edge: a binding tier cap yields 'modified' with TIER_CAP."""
    p = params_with(tier_caps={"core": D(10)})
    ctx = make_ctx(params=p)
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert rd.status == RiskStatus.MODIFIED and rd.binding_constraint.value == "TIER_CAP"
    assert rd.approved_notional_usd <= D(250)


def test_no_headroom_rejected() -> None:
    """Failure: zero headroom rejects with the binding limit's code."""
    p = params_with(tier_caps={"core": D(10)})
    ctx = make_ctx(params=p, holdings={"BTC-USD": (D(3), D(100))})
    # held BTC means RR-07 already-long; use ETH exposure against the total cap instead
    p2 = params_with(total_exposure_pct=D(10))
    ctx = make_ctx(params=p2, holdings={"ETH-USD": (D(3), D(100))})
    rd = RiskEngine().evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    assert rd.reason_codes[0].value == "EXPOSURE_LIMIT"
    _ = BASE_COSTS
