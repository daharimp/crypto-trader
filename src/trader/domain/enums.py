"""Enumerations and reason codes (§7.2)."""

from __future__ import annotations

from enum import StrEnum


class Environment(StrEnum):
    """Execution environments.

    ``live`` sends real orders to an exchange. It exists only behind the gates in ADR-023:
    an active profile with ``real_money_enabled``, an owner-signed live authorization with a
    capital cap, a live activation record, and the Kraken adapter. Spot only.
    """

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Side(StrEnum):
    """Order side. Sells only reduce existing longs (spot long-only)."""

    BUY = "buy"
    SELL = "sell"


class Sleeve(StrEnum):
    """Capital sleeve."""

    CORE = "core"
    INTRADAY = "intraday"


class OrderPurpose(StrEnum):
    """Why an order exists."""

    ENTRY = "entry"
    EXIT = "exit"
    PROTECTIVE_STOP = "protective_stop"


class OrderType(StrEnum):
    """Supported simulated order types."""

    MARKET = "market"
    STOP_MARKET = "stop_market"
    LIMIT = "limit"  # post-only limit (maker); simulator and paper only so far


class EnsembleAction(StrEnum):
    """Ensemble outcome per instrument and cycle."""

    ENTER_LONG = "enter_long"
    EXIT_LONG = "exit_long"
    HOLD = "hold"
    NO_TRADE = "no_trade"


class NoTradeReason(StrEnum):
    """Why the ensemble chose not to trade."""

    SIGNAL_CONFLICT = "SIGNAL_CONFLICT"
    REGIME_BLOCKED = "REGIME_BLOCKED"
    DATA_STALE = "DATA_STALE"
    DATA_UNCERTAIN = "DATA_UNCERTAIN"
    NO_ELIGIBLE_SIGNALS = "NO_ELIGIBLE_SIGNALS"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"


class RiskStatus(StrEnum):
    """Risk decision status."""

    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"


class RuleOutcome(StrEnum):
    """Result of one risk rule."""

    PASS = "pass"
    FAIL = "fail"
    CLAMPED = "clamped"
    NOT_EVALUATED = "not_evaluated"
    NOT_APPLICABLE = "not_applicable"


class BindingConstraint(StrEnum):
    """The limit that reduced an entry size."""

    TIER_CAP = "TIER_CAP"
    SPECULATIVE_CAP = "SPECULATIVE_CAP"
    TOTAL_EXPOSURE_CAP = "TOTAL_EXPOSURE_CAP"
    RESERVE_FLOOR = "RESERVE_FLOOR"
    AVAILABLE_CASH = "AVAILABLE_CASH"


class ExecutionStatus(StrEnum):
    """Order lifecycle states."""

    ACCEPTED = "accepted"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ERROR = "error"


class Provenance(StrEnum):
    """Where an effective configuration value came from."""

    APPROVED = "approved"
    HYPOTHESIS = "hypothesis"
    EXPERIMENT = "experiment"
    FIXTURE = "fixture"


class TrendState(StrEnum):
    """Regime trend dimension."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE_BOUND = "range_bound"
    UNKNOWN = "unknown"


class VolatilityState(StrEnum):
    """Regime volatility dimension."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    UNKNOWN = "unknown"


class DataState(StrEnum):
    """Regime data-quality dimension."""

    OK = "ok"
    UNCERTAIN = "uncertain"
    STALE = "stale"


class RegimeMethod(StrEnum):
    """How a regime assessment was produced."""

    NOT_EVALUATED = "not_evaluated"
    DETERMINISTIC_RULES = "deterministic_rules"
    ML_MODEL = "ml_model"
    AI_ASSISTED = "ai_assisted"


class ReasonCode(StrEnum):
    """Risk and execution rejection codes."""

    PROFILE_NOT_RUNNABLE = "PROFILE_NOT_RUNNABLE"
    RISK_CONFIG_UNRESOLVED = "RISK_CONFIG_UNRESOLVED"
    KILL_SWITCH_ENGAGED = "KILL_SWITCH_ENGAGED"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    ASSET_NOT_SUPPORTED = "ASSET_NOT_SUPPORTED"
    ASSET_BLOCKED = "ASSET_BLOCKED"
    ASSET_INELIGIBLE = "ASSET_INELIGIBLE"
    STALE_DATA = "STALE_DATA"
    DATA_QUALITY_FAILED = "DATA_QUALITY_FAILED"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    SPOT_CONSTRAINT_VIOLATION = "SPOT_CONSTRAINT_VIOLATION"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    INTRADAY_SLEEVE_DISABLED = "INTRADAY_SLEEVE_DISABLED"
    CONCENTRATION_LIMIT = "CONCENTRATION_LIMIT"
    EXPOSURE_LIMIT = "EXPOSURE_LIMIT"
    RESERVE_LIMIT = "RESERVE_LIMIT"
    MAX_POSITIONS = "MAX_POSITIONS"
    SIZE_BELOW_MINIMUM = "SIZE_BELOW_MINIMUM"
    EXCESSIVE_SIZE = "EXCESSIVE_SIZE"
    RISK_DECISION_MISSING = "RISK_DECISION_MISSING"
    RISK_DECISION_MISMATCH = "RISK_DECISION_MISMATCH"
    ADAPTER_NOT_ALLOWED = "ADAPTER_NOT_ALLOWED"
    INTENT_EXPIRED = "INTENT_EXPIRED"
    EXCHANGE_ERROR = "EXCHANGE_ERROR"
    LIMIT_NOT_FILLED = "LIMIT_NOT_FILLED"


class ValidationErrorCode(StrEnum):
    """Compiler and CLI validation codes (exit 2 unless noted)."""

    SCHEMA_INVALID = "SCHEMA_INVALID"
    SAFETY_CONSTANT_VIOLATION = "SAFETY_CONSTANT_VIOLATION"
    PROFILE_CONTRADICTION = "PROFILE_CONTRADICTION"
    RISK_PROFILE_CONTRADICTION = "RISK_PROFILE_CONTRADICTION"
    AGGRESSIVE_NOT_ACKNOWLEDGED = "AGGRESSIVE_NOT_ACKNOWLEDGED"
    RISK_PROFILE_NOT_FOUND = "RISK_PROFILE_NOT_FOUND"
    INTRADAY_NOT_APPROVED = "INTRADAY_NOT_APPROVED"
    DATA_SOURCE_NOT_PERMITTED = "DATA_SOURCE_NOT_PERMITTED"
    PROFILE_NOT_RUNNABLE = "PROFILE_NOT_RUNNABLE"
    PROFILE_VERSION_NOT_INCREMENTED = "PROFILE_VERSION_NOT_INCREMENTED"
    EXPERIMENT_PARAMETERS_REJECTED = "EXPERIMENT_PARAMETERS_REJECTED"
    NAIVE_TIMESTAMP = "NAIVE_TIMESTAMP"
    DATA_QUALITY_FAILED = "DATA_QUALITY_FAILED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    RISK_CONFIG_UNRESOLVED = "RISK_CONFIG_UNRESOLVED"
    DATASET_INTEGRITY_FAILED = "DATASET_INTEGRITY_FAILED"
    JOURNAL_INTEGRITY_FAILED = "JOURNAL_INTEGRITY_FAILED"
    LIVE_NOT_AUTHORIZED = "LIVE_NOT_AUTHORIZED"
    LIVE_NOT_ACKNOWLEDGED = "LIVE_NOT_ACKNOWLEDGED"


class EventType(StrEnum):
    """Journal event types."""

    RUN_STARTED = "RUN_STARTED"
    RUN_BLOCKED = "RUN_BLOCKED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    PROFILE_COMPILED = "PROFILE_COMPILED"
    DATASET_VALIDATED = "DATASET_VALIDATED"
    UNIVERSE_EVALUATED = "UNIVERSE_EVALUATED"
    CYCLE_STARTED = "CYCLE_STARTED"
    DATA_STALE = "DATA_STALE"
    PROVIDER_DEGRADED = "PROVIDER_DEGRADED"
    FEATURES_COMPUTED = "FEATURES_COMPUTED"
    REGIME_ASSESSED = "REGIME_ASSESSED"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    ENSEMBLE_DECIDED = "ENSEMBLE_DECIDED"
    RISK_EVALUATED = "RISK_EVALUATED"
    ORDER_INTENT_CREATED = "ORDER_INTENT_CREATED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELED = "ORDER_CANCELED"
    STOP_TRIGGERED = "STOP_TRIGGERED"
    POSITION_UPDATED = "POSITION_UPDATED"
    CIRCUIT_BREAKER_OPENED = "CIRCUIT_BREAKER_OPENED"
    DAILY_LOCKOUT_STARTED = "DAILY_LOCKOUT_STARTED"
    COOLDOWN_STARTED = "COOLDOWN_STARTED"
    KILL_SWITCH_ENGAGED = "KILL_SWITCH_ENGAGED"
    KILL_SWITCH_DISENGAGED = "KILL_SWITCH_DISENGAGED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    EXPLANATION_GENERATED = "EXPLANATION_GENERATED"
    CYCLE_COMPLETED = "CYCLE_COMPLETED"
