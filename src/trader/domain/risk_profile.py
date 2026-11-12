"""RiskProfile contract, mirroring ``schemas/risk-profile.schema.yaml`` (D-08 to D-14).

Values that the owner has not decided are ``TBD``. Constants are ``Literal`` types and can
never be changed by configuration or experiments.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import DomainModel, RiskProfileId, SchemaVersion
from .params import (
    ChoiceParam,
    CountParam,
    GenericParam,
    HoursParam,
    LossScalingSchedule,
    MultiplierParam,
    PctParam,
    PctRangeParam,
    SecondsParam,
    StopPolicy,
)


class Selection(DomainModel):
    """How the profile may be selected (D-06, D-09)."""

    initial_default: bool
    explicit_selection_required: bool


class GlobalHardConstraints(DomainModel):
    """Safety constants (D-02, D-03, D-13, D-14)."""

    funds: Literal["simulated"]
    instrument_types: Annotated[list[Literal["spot"]], Field(min_length=1, max_length=1)]
    leverage_allowed: Literal[False]
    margin_allowed: Literal[False]
    short_selling_allowed: Literal[False]
    withdrawals_allowed: Literal[False]
    deterministic_final_authority: Literal[True]
    ai_may_override_limits: Literal[False]
    profile_switching: Literal["owner_only"]


class LossResponse(DomainModel):
    """Hybrid loss handling (D-12)."""

    reassess_signals_and_conditions_each_cycle: Literal[True]
    size_reduction_schedule: LossScalingSchedule
    hard_thresholds_override_all: Literal[True]
    circuit_breaker_stops_new_trades: Literal[True]


class Limits(DomainModel):
    """Portfolio loss limits (UD-01, UD-02)."""

    portfolio_drawdown_circuit_breaker_pct: PctParam
    daily_loss_limit_pct: PctParam
    daily_loss_window: Literal["utc_calendar_day"]
    circuit_breaker_reset: Literal["owner_command_with_reason"]


class Adaptation(DomainModel):
    """Sizing adaptation bounds (D-10)."""

    downward: Literal["loss_response_schedule"]
    upward_enabled: bool
    upward_multiplier_max: MultiplierParam


class Sizing(DomainModel):
    """Per-trade sizing inputs (UD-03, UD-16)."""

    risk_per_trade_pct: PctParam
    hard_stop_policy: StopPolicy
    adaptation: Adaptation
    quantity_rounding: Literal["round_down_to_instrument_step"]


class Concentration(DomainModel):
    """Tier caps (H-01 to H-04 for Balanced)."""

    applies_to: Literal["aggregate_exposure_across_sleeves"]
    core_per_asset_cap_pct: PctParam
    major_per_asset_cap_pct: PctParam
    speculative_per_asset_cap_pct: PctParam
    speculative_total_cap_pct: PctParam


class IntradaySleeveLimits(DomainModel):
    """Isolated intraday sleeve limits (D-19, UD-14)."""

    isolation: Literal["separate_ledger_no_borrowing_from_core"]
    daily_loss_limit_pct: PctParam
    drawdown_circuit_breaker_pct: PctParam


class Allocation(DomainModel):
    """Exposure, reserve, and position-count limits (UD-04, UD-12, UD-14)."""

    total_exposure_cap_pct: PctParam
    minimum_reserve_pct_range: PctRangeParam
    max_open_positions: CountParam
    intraday_allocation_cap_pct: PctParam
    intraday_sleeve_limits: IntradaySleeveLimits


class ConsecutiveLossCooldown(DomainModel):
    """Cooldown after consecutive losing trades (UD-17)."""

    scope: Literal["strategy_instrument"]
    count: CountParam
    duration_hours: HoursParam


class Cooldown(DomainModel):
    """Cooldown rules."""

    after_consecutive_losing_trades: ConsecutiveLossCooldown


class StaleData(DomainModel):
    """Stale-data handling."""

    definition: Literal["missing_latest_expected_closed_candle"]
    action: Literal["block_new_orders_for_instrument"]
    paper_grace_seconds: SecondsParam
    escalate_to_kill_switch_after_stale_cycles: CountParam


class ExchangeErrors(DomainModel):
    """Execution-error handling."""

    retry_policy: Literal["idempotent_operations_only"]
    max_consecutive_errors_before_kill_switch: CountParam


class Reconciliation(DomainModel):
    """Reconciliation tolerances."""

    internal_simulator: Literal["exact_match"]
    external_adapter_quantity_tolerance: GenericParam


class DataAndExecutionFaults(DomainModel):
    """Fault handling."""

    stale_data: StaleData
    exchange_errors: ExchangeErrors
    clock_skew_tolerance_seconds: SecondsParam
    reconciliation: Reconciliation


class KillSwitchStateModel(DomainModel):
    """Kill-switch state model."""

    values: list[Literal["disengaged", "engaged"]]
    source: Literal["operational_store"]
    persisted_across_restarts: Literal[True]
    initial_state_on_first_start: Literal["disengaged"]


class KillSwitchPolicy(DomainModel):
    """Kill-switch policy (D-35). Automation can only engage."""

    state_model: KillSwitchStateModel
    manual_engage: Literal["always_available"]
    manual_disengage: Literal["owner_command_with_reason"]
    automated_disengage_allowed: Literal[False]
    ai_may_change_state: Literal[False]
    effect_on_new_orders: Literal["block_all"]
    auto_engage_triggers: list[
        Literal[
            "reconciliation_mismatch",
            "repeated_execution_errors",
            "clock_skew_exceeded",
            "journal_write_failure",
            "risk_config_invalid_mid_session",
            "persistent_stale_data",
        ]
    ]


class HaltAndLiquidation(DomainModel):
    """Behavior after a halt (UD-19)."""

    interim_behavior_until_resolved: Literal["hold_unchanged_including_attached_stops"]
    liquidation_policy_after_halt: ChoiceParam


class RiskProfile(DomainModel):
    """Deterministic risk boundaries for one selectable profile (contract 2)."""

    schema_version: SchemaVersion
    kind: Literal["RiskProfile"]
    risk_profile_id: RiskProfileId
    version: Annotated[int, Field(ge=1)]
    display_name: Annotated[str, Field(min_length=1)]
    description: str | None = None
    selection: Selection
    global_hard_constraints: GlobalHardConstraints
    loss_response: LossResponse
    limits: Limits
    sizing: Sizing
    concentration: Concentration
    allocation: Allocation
    cooldown: Cooldown
    data_and_execution_faults: DataAndExecutionFaults
    kill_switch: KillSwitchPolicy
    halt_and_liquidation: HaltAndLiquidation
