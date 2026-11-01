"""Typed view of the resolved risk values in a CompiledProfile.

No defaults exist here: a missing value yields ``None`` and the engine rejects with
``RISK_CONFIG_UNRESOLVED`` (rule 3 of the handoff: never invent risk values).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from trader.domain.compiled import CompiledProfile


@dataclass(frozen=True)
class StopPolicyParams:
    """Resolved hard-stop policy (UD-16)."""

    method: str
    atr_period_bars: int | None
    atr_multiple: Decimal | None
    fixed_pct: Decimal | None


@dataclass(frozen=True)
class RiskParams:
    """Every risk value the M1 engine reads."""

    breaker_pct: Decimal
    daily_loss_pct: Decimal
    risk_per_trade_pct: Decimal
    stop: StopPolicyParams
    schedule_method: str
    schedule_steps: tuple[tuple[Decimal, Decimal], ...]
    tier_caps: dict[str, Decimal]
    speculative_total_pct: Decimal | None
    total_exposure_pct: Decimal
    reserve_low_pct: Decimal
    reserve_high_pct: Decimal
    max_open_positions: int
    cooldown_count: int
    cooldown_hours: Decimal
    max_consecutive_errors: int


def _dec(value: Any) -> Decimal:
    """
    Convert a resolved value to Decimal.

    Args:
        value (Any): int, str, or Decimal.

    Returns:
        Decimal: Value.
    """
    return value if isinstance(value, Decimal) else Decimal(str(value))


def risk_params_from_compiled(compiled: CompiledProfile) -> RiskParams | None:
    """
    Build RiskParams from a compiled profile.

    Args:
        compiled (CompiledProfile): Compiled profile.

    Returns:
        RiskParams | None: Parameters, or None if any required value is unresolved.
    """
    eff = compiled.effective

    def get(key: str) -> Any:
        ev = eff.get(f"risk.{key}")
        return None if ev is None else ev.value

    required = [
        "limits.portfolio_drawdown_circuit_breaker_pct",
        "limits.daily_loss_limit_pct",
        "sizing.risk_per_trade_pct",
        "sizing.hard_stop_policy",
        "loss_response.size_reduction_schedule",
        "allocation.total_exposure_cap_pct",
        "allocation.minimum_reserve_pct_range",
        "allocation.max_open_positions",
        "cooldown.after_consecutive_losing_trades.count",
        "cooldown.after_consecutive_losing_trades.duration_hours",
        "data_and_execution_faults.exchange_errors.max_consecutive_errors_before_kill_switch",
    ]
    if compiled.blockers or any(get(k) is None for k in required):
        return None
    stop = get("sizing.hard_stop_policy")
    sched = get("loss_response.size_reduction_schedule")
    steps_raw = sched["steps"] if isinstance(sched["steps"], list) else []
    caps = {
        t: _dec(v)
        for t in ("core", "major", "speculative")
        if (v := get(f"concentration.{t}_per_asset_cap_pct")) is not None
    }
    spec_total = get("concentration.speculative_total_cap_pct")
    reserve = get("allocation.minimum_reserve_pct_range")
    return RiskParams(
        breaker_pct=_dec(get("limits.portfolio_drawdown_circuit_breaker_pct")),
        daily_loss_pct=_dec(get("limits.daily_loss_limit_pct")),
        risk_per_trade_pct=_dec(get("sizing.risk_per_trade_pct")),
        stop=StopPolicyParams(
            method=str(stop["method"]),
            atr_period_bars=int(stop["atr_period_bars"]) if "atr_period_bars" in stop else None,
            atr_multiple=_dec(stop["atr_multiple"]) if "atr_multiple" in stop else None,
            fixed_pct=_dec(stop["fixed_pct"]) if "fixed_pct" in stop else None,
        ),
        schedule_method=str(sched["method"]),
        schedule_steps=tuple(
            (_dec(s["drawdown_fraction_of_breaker_below"]), _dec(s["multiplier"]))
            for s in steps_raw
        ),
        tier_caps=caps,
        speculative_total_pct=None if spec_total is None else _dec(spec_total),
        total_exposure_pct=_dec(get("allocation.total_exposure_cap_pct")),
        reserve_low_pct=_dec(reserve["low"]),
        reserve_high_pct=_dec(reserve["high"]),
        max_open_positions=int(get("allocation.max_open_positions")),
        cooldown_count=int(get("cooldown.after_consecutive_losing_trades.count")),
        cooldown_hours=_dec(get("cooldown.after_consecutive_losing_trades.duration_hours")),
        max_consecutive_errors=int(
            get(
                "data_and_execution_faults.exchange_errors.max_consecutive_errors_before_kill_switch"
            )
        ),
    )
