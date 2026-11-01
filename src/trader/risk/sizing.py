"""Deterministic sizing RR-13 to RR-20 (handoff §7.8, strategy-spec.md §9).

All arithmetic is Decimal. Strategies never size; only this module does (D-32).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trader.common.decimal_utils import round_down_to_step
from trader.domain.enums import BindingConstraint, ReasonCode, RuleOutcome
from trader.domain.risk import RuleResult, StopSpec

from .context import RiskContext
from .rules import fail, ok, result

HUNDRED = Decimal(100)
R = ReasonCode
B = BindingConstraint


@dataclass
class SizingResult:
    """Outcome of RR-13 to RR-20."""

    rules: list[RuleResult]
    quantity: Decimal
    notional: Decimal
    stop: StopSpec | None
    binding: BindingConstraint | None
    rejected: ReasonCode | None


def _stop_distance(ctx: RiskContext, price: Decimal) -> tuple[Decimal | None, StopSpec | None, str]:
    """
    Hard-stop distance as a fraction of price (RR-14 input, UD-16).

    Args:
        ctx (RiskContext): Context.
        price (Decimal): Latest close.

    Returns:
        tuple[Decimal | None, StopSpec | None, str]: Distance, spec, and a failure detail.
    """
    assert ctx.params is not None
    sp = ctx.params.stop
    if sp.method == "atr_multiple":
        atr = ctx.features.values.get("atr_14") if ctx.features else None
        if sp.atr_period_bars != 14:
            return None, None, "atr_period_unsupported_by_features_m1"
        if atr is None or sp.atr_multiple is None:
            return None, None, "stop_inputs_missing"
        d = sp.atr_multiple * atr / price
        spec = StopSpec(method="atr_multiple", stop_distance_pct=d * HUNDRED, atr_value=atr)
    elif sp.method == "fixed_pct" and sp.fixed_pct is not None:
        d = sp.fixed_pct / HUNDRED
        spec = StopSpec(method="fixed_pct", stop_distance_pct=sp.fixed_pct, atr_value=None)
    else:
        return None, None, "stop_inputs_missing"
    if d <= 0 or d >= 1:
        return None, None, "stop_distance_out_of_range"
    return d, spec, ""


def size_entry(ctx: RiskContext) -> SizingResult:
    """
    Compute the approved entry quantity.

    Args:
        ctx (RiskContext): Context (params must be resolved).

    Returns:
        SizingResult: Rules, quantity, notional, stop, binding constraint, rejection code.
    """
    assert ctx.params is not None and ctx.snapshot.latest_bar is not None
    p = ctx.params
    iid = ctx.snapshot.instrument_id
    rules: list[RuleResult] = []
    E = ctx.position.equity_usd
    C, K = ctx.position.cash_usd, ctx.position.committed_cash_usd
    P = ctx.snapshot.latest_bar.close
    tier = ctx.registry.tier_of(iid) or "unknown"

    def done(code: ReasonCode, stop: StopSpec | None = None) -> SizingResult:
        done_ids = {r.rule_id for r in rules}
        for rid in (f"RR-{n}" for n in range(13, 21)):
            if rid not in done_ids:
                rules.append(result(rid, RuleOutcome.NOT_EVALUATED))
        return SizingResult(rules, Decimal(0), Decimal(0), stop, None, code)

    # RR-13 loss scaling
    m_loss = ctx.loss.loss_scaling_multiplier
    rules.append(ok("RR-13", multiplier=m_loss, drawdown_pct=ctx.loss.drawdown_pct))
    # RR-14 risk budget / stop distance
    stop_d, stop, why = _stop_distance(ctx, P)
    if stop_d is None:
        rules.append(fail("RR-14", R.RISK_CONFIG_UNRESOLVED, detail=why))
        return done(R.RISK_CONFIG_UNRESOLVED)
    budget = E * p.risk_per_trade_pct / HUNDRED * m_loss
    n_risk = budget / stop_d
    rules.append(ok("RR-14", budget_usd=budget, stop_distance=stop_d, n_risk=n_risk))
    # RR-15 to RR-18 headroom
    cap = p.tier_caps.get(tier)
    if cap is None:
        rules.append(fail("RR-15", R.RISK_CONFIG_UNRESOLVED, tier=tier, why="tier_cap_missing"))
        return done(R.RISK_CONFIG_UNRESOLVED, stop)
    h_tier = E * cap / HUNDRED - ctx.market_value(iid) - ctx.pending_notional(iid)
    candidates: list[tuple[Decimal, BindingConstraint | None, ReasonCode, str]] = [
        (n_risk, None, R.SIZE_BELOW_MINIMUM, "RR-14"),
        (h_tier, B.TIER_CAP, R.CONCENTRATION_LIMIT, "RR-15"),
    ]
    if tier == "speculative":
        if p.speculative_total_pct is None:
            rules.append(fail("RR-16", R.RISK_CONFIG_UNRESOLVED, why="speculative_total_missing"))
            return done(R.RISK_CONFIG_UNRESOLVED, stop)
        h_spec = (
            E * p.speculative_total_pct / HUNDRED
            - ctx.market_value(tier="speculative")
            - ctx.pending_notional(tier="speculative")
        )
        candidates.append((h_spec, B.SPECULATIVE_CAP, R.CONCENTRATION_LIMIT, "RR-16"))
    h_total = E * p.total_exposure_pct / HUNDRED - ctx.market_value() - ctx.pending_notional()
    candidates.append((h_total, B.TOTAL_EXPOSURE_CAP, R.EXPOSURE_LIMIT, "RR-17"))
    h_cash = (C - K - E * p.reserve_low_pct / HUNDRED) / (1 + ctx.costs.fee_rate)
    cash_binding = B.RESERVE_FLOOR if p.reserve_low_pct > 0 else B.AVAILABLE_CASH
    candidates.append((h_cash, cash_binding, R.RESERVE_LIMIT, "RR-18"))
    # Reason: min() keeps the first of equal values, so N_risk wins ties -> "approved".
    n, binding, code, rid = min(candidates, key=lambda c: c[0])
    for value, b, _c, r_id in candidates[1:]:
        clamped = b == binding and value < n_risk
        rules.append(
            result(
                r_id, RuleOutcome.CLAMPED if clamped else RuleOutcome.PASS, None, headroom_usd=value
            )
        )
    if tier != "speculative":
        rules.append(result("RR-16", RuleOutcome.NOT_APPLICABLE, None, tier=tier))
    rules.sort(key=lambda r: r.rule_id)
    if n <= 0:
        rules[:] = [r for r in rules if r.rule_id != rid] + [fail(rid, code, headroom_usd=n)]
        rules.sort(key=lambda r: r.rule_id)
        return done(code, stop)
    # RR-19 max open positions (including pending entries)
    open_count = ctx.position.open_positions_count + len(ctx.pending_entries())
    if open_count >= p.max_open_positions:
        rules.append(fail("RR-19", R.MAX_POSITIONS, open=open_count, max=p.max_open_positions))
        return done(R.MAX_POSITIONS, stop)
    rules.append(ok("RR-19", open=open_count, max=p.max_open_positions))
    # RR-20 minimum notional after clamping and rounding
    inst = ctx.registry.instrument(iid)
    assert inst is not None
    p_cons = P * (1 + ctx.costs.slippage)
    qty = round_down_to_step(n / p_cons, inst.quantity_step)
    notional = qty * p_cons
    if notional < ctx.costs.min_notional_usd or qty <= 0:
        rules.append(
            fail("RR-20", R.SIZE_BELOW_MINIMUM, notional=notional, min=ctx.costs.min_notional_usd)
        )
        return done(R.SIZE_BELOW_MINIMUM, stop)
    rules.append(ok("RR-20", notional=notional, min=ctx.costs.min_notional_usd))
    return SizingResult(rules, qty, notional, stop, binding, None)
