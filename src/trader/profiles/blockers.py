"""Required-field sets per environment and blocker detection (§7.4.1, RP-11)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from trader.domain.compiled import Blocker, EffectiveValue
from trader.domain.enums import Environment

_BACKTEST_RISK = [
    "limits.portfolio_drawdown_circuit_breaker_pct",
    "limits.daily_loss_limit_pct",
    "loss_response.size_reduction_schedule",
    "sizing.risk_per_trade_pct",
    "sizing.hard_stop_policy",
    "allocation.total_exposure_cap_pct",
    "allocation.minimum_reserve_pct_range",
    "allocation.max_open_positions",
    "cooldown.after_consecutive_losing_trades.count",
    "cooldown.after_consecutive_losing_trades.duration_hours",
    "data_and_execution_faults.exchange_errors.max_consecutive_errors_before_kill_switch",
]
_PAPER_RISK = [
    "data_and_execution_faults.stale_data.paper_grace_seconds",
    "data_and_execution_faults.stale_data.escalate_to_kill_switch_after_stale_cycles",
    "data_and_execution_faults.clock_skew_tolerance_seconds",
    "halt_and_liquidation.liquidation_policy_after_halt",
]


def iter_param_nodes(tree: Any, prefix: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """
    Yield every parameter node (a mapping with ``status`` and ``ref``) with its dotted path.

    Args:
        tree (Any): Parsed configuration mapping.
        prefix (str): Path prefix for recursion.

    Yields:
        tuple[str, dict[str, Any]]: ``(dotted_path, node)``.
    """
    if not isinstance(tree, dict):
        return
    if "status" in tree and "ref" in tree:
        yield prefix, tree
        return
    for key, value in tree.items():
        yield from iter_param_nodes(value, f"{prefix}.{key}" if prefix else str(key))


def required_fields(environment: Environment, tiers: set[str]) -> list[str]:
    """
    List the effective-value keys a run in ``environment`` needs.

    Args:
        environment (Environment): Target environment.
        tiers (set[str]): Tiers present among the in-scope instruments.

    Returns:
        list[str]: Keys such as ``risk.limits.daily_loss_limit_pct``.
    """
    keys = [f"risk.{p}" for p in _BACKTEST_RISK]
    for tier in sorted(tiers & {"core", "major", "speculative"}):
        keys.append(f"risk.concentration.{tier}_per_asset_cap_pct")
        keys.append(f"eligibility.liquidity.min_by_tier.{tier}")
        keys.append(f"eligibility.data_history.min_by_tier.{tier}")
    if "speculative" in tiers:
        keys.append("risk.concentration.speculative_total_cap_pct")
    # Reason: M1 has no spread provider, so the "no spread data" policy is always needed.
    keys.append("eligibility.spread.when_no_spread_data")
    if environment in (Environment.PAPER, Environment.LIVE):
        keys.extend(f"risk.{p}" for p in _PAPER_RISK)
    if environment == Environment.LIVE:
        keys.extend(["live.max_capital_usd", "live.min_paper_cycles_before_live"])
    return keys


def find_blockers(
    required: list[str],
    effective: dict[str, EffectiveValue],
    refs: dict[str, str],
) -> list[Blocker]:
    """
    Return a blocker for every required key that has no effective value.

    Args:
        required (list[str]): Required keys.
        effective (dict[str, EffectiveValue]): Resolved values.
        refs (dict[str, str]): Decision reference (``UD-nn``) for every known key.

    Returns:
        list[Blocker]: Blockers sorted by field.
    """
    out = [
        Blocker(field=k, ref=refs.get(k, "UNKNOWN"), reason="RISK_CONFIG_UNRESOLVED")
        for k in required
        if k not in effective
    ]
    return sorted(out, key=lambda b: b.field)
