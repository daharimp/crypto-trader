"""TradingProfile contract, mirroring ``schemas/trading-profile.schema.yaml``.

Safety constants are ``Literal`` types, so real money, leverage, margin, short selling,
withdrawals, and transfers are unrepresentable (D-02, D-03).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .common import DomainModel, SchemaVersion

AssetId = Annotated[str, Field(pattern=r"^[A-Z0-9]{2,15}$")]
InstrumentId = Annotated[str, Field(pattern=r"^[A-Z0-9]{2,15}-[A-Z0-9]{2,10}$")]
UtcText = Annotated[
    str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$")
]
ProfileStatus = Literal["draft", "validated", "active", "suspended"]
Tier = Literal["core", "major", "speculative"]


class StatusChange(DomainModel):
    """Human-maintained status history entry."""

    status: ProfileStatus
    changed_at_utc: UtcText
    changed_by: Annotated[str, Field(min_length=1)]
    reason: Annotated[str, Field(min_length=1)]


class Objective(DomainModel):
    """APPROVED D-05 objective; D-07 no guaranteed profitability."""

    objective_id: Literal["balance_returns_consistency_drawdown"]
    statement: Literal[
        "Balance strong returns with consistent performance and controlled drawdown."
    ]
    guaranteed_profitability_assumed: Literal[False]
    decision_ref: Literal["D-05"]


class Capital(DomainModel):
    """Simulated capital (D-04); funds are always simulated (D-02)."""

    paper_capital_usd: Annotated[Decimal, Field(gt=0)]
    accounting_currency: Literal["USD"]
    funds: Literal["simulated"]


class AggressiveAcknowledgement(DomainModel):
    """Owner's explicit acknowledgement for the Aggressive profile (D-06)."""

    acknowledged: Literal[True]
    acknowledged_by: Annotated[str, Field(min_length=1)]
    acknowledged_at_utc: UtcText
    statement: Annotated[str, Field(min_length=20)]


class RiskSelection(DomainModel):
    """Owner's risk-profile selection (D-08 to D-10)."""

    risk_profile_id: Literal["conservative", "balanced", "aggressive"]
    risk_profile_version: Annotated[int, Field(ge=1)]
    adaptation: Literal["within_selected_profile_bounds"]
    profile_switching: Literal["owner_only"]
    aggressive_acknowledgement: AggressiveAcknowledgement | None = None


class AllowlistEntry(DomainModel):
    """Owner-nominated asset (D-24); still subject to eligibility (D-25)."""

    asset_id: AssetId
    nominated_by: Annotated[str, Field(min_length=1)]
    nominated_at_utc: UtcText
    note: str | None = None


class Universe(DomainModel):
    """Rules-based tiered universe (D-22 to D-26)."""

    construction: Literal["rules_based", "rules_based_with_dynamic_discovery"]
    quote_currency: Literal["USD"]
    allowed_tiers: Annotated[list[Tier], Field(min_length=1)]
    core_assets: list[AssetId]
    manual_allowlist: list[AllowlistEntry]
    disallowed_assets: list[AssetId]
    instruments_in_scope: Annotated[list[InstrumentId], Field(min_length=1)]
    eligibility_required_for_all: Literal[True]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        """
        Enforce ``uniqueItems`` on list fields.

        Returns:
            Universe: The validated universe.

        Raises:
            ValueError: If a list contains duplicates.
        """
        for name in ("allowed_tiers", "core_assets", "disallowed_assets", "instruments_in_scope"):
            items = getattr(self, name)
            if len(set(items)) != len(items):
                raise ValueError(f"{name} must be unique")
        return self


class TypicalHolding(DomainModel):
    """APPROVED D-17 description; not an enforced limit."""

    description: Literal["From roughly one hour through several days"]
    enforced_limit: Literal[False]


class MinuteData(DomainModel):
    """Permitted roles for minute-level data (D-18)."""

    permitted_roles: list[Literal["entry_exit_refinement", "approved_intraday_strategies"]]
    entry_exit_refinement_enabled: bool
    intraday_strategies_enabled: bool


class Horizon(DomainModel):
    """Holding period and timeframes (D-15, D-16, D-21)."""

    holding_period: Literal["adaptive"]
    primary_decision_timeframes: Annotated[list[Literal["1h", "4h"]], Field(min_length=1)]
    typical_holding: TypicalHolding
    minute_data: MinuteData
    excluded_styles: list[Literal["high_frequency", "latency_arbitrage"]]

    @model_validator(mode="after")
    def _both_excluded(self) -> Self:
        """
        Require both high-frequency and latency arbitrage to be excluded (D-21).

        Returns:
            Horizon: The validated horizon.

        Raises:
            ValueError: If either style is missing.
        """
        if set(self.excluded_styles) != {"high_frequency", "latency_arbitrage"}:
            raise ValueError("excluded_styles must list high_frequency and latency_arbitrage")
        return self


class Execution(DomainModel):
    """Execution settings.

    Leverage, margin, short selling, withdrawals, and transfers are constant false (SAFE-02,
    SAFE-03). ``real_money_enabled`` must be true exactly when ``live`` is permitted (ADR-023).
    """

    permitted_environments: Annotated[
        list[Literal["backtest", "paper", "live"]], Field(min_length=1)
    ]
    autonomy_mode: Literal["paper_autonomous", "observe_only"]
    per_trade_approval_required: Literal[False]
    instrument_types: Annotated[list[Literal["spot"]], Field(min_length=1, max_length=1)]
    real_money_enabled: bool
    leverage_allowed: Literal[False]
    margin_allowed: Literal[False]
    short_selling_allowed: Literal[False]
    withdrawals_allowed: Literal[False]
    transfers_allowed: Literal[False]

    @model_validator(mode="after")
    def _real_money_matches_live(self) -> Self:
        """
        Require ``real_money_enabled`` if and only if ``live`` is permitted.

        Returns:
            Execution: The validated execution settings.

        Raises:
            ValueError: If the flag and the permitted environments disagree.
        """
        if self.real_money_enabled != ("live" in self.permitted_environments):
            raise ValueError("real_money_enabled must be true exactly when 'live' is permitted")
        if len(set(self.permitted_environments)) != len(self.permitted_environments):
            raise ValueError("permitted_environments must be unique")
        return self


class Explanations(DomainModel):
    """Explanation preference (R-13)."""

    preference: Literal["every_decision", "orders_and_rejections", "orders_only"]
    narrative_source: Literal["recorded_facts_only"]
    ai_generated_narratives_enabled: bool


_SOURCE_TIER = {
    "market_candles": "V1",
    "order_book": "V1.5",
    "cross_asset": "V1.5",
    "derivatives_data": "V1.5",
    "news": "V2",
    "on_chain": "V2",
    "macro": "V2",
    "social_sentiment": "experimental",
    "alternative_signals": "experimental",
}


class DataSourceRef(DomainModel):
    """An active data source and its roadmap tier (D-37, D-38)."""

    source_id: Literal[
        "market_candles",
        "order_book",
        "cross_asset",
        "derivatives_data",
        "news",
        "on_chain",
        "macro",
        "social_sentiment",
        "alternative_signals",
    ]
    tier: Literal["V1", "V1.5", "V2", "experimental"]
    required_for_trading: bool

    @model_validator(mode="after")
    def _tier_matches(self) -> Self:
        """
        Check the source's tier and the experimental-source rule.

        Returns:
            DataSourceRef: The validated source.

        Raises:
            ValueError: If the tier does not match the source or an experimental source is
                required for trading.
        """
        if _SOURCE_TIER[self.source_id] != self.tier:
            raise ValueError(f"{self.source_id} must be tier {_SOURCE_TIER[self.source_id]}")
        if self.tier == "experimental" and self.required_for_trading:
            raise ValueError("experimental sources cannot be required_for_trading")
        return self


class DataSources(DomainModel):
    """Active data sources."""

    active: Annotated[list[DataSourceRef], Field(min_length=1)]


class TradingProfile(DomainModel):
    """Owner-authored description of what the paper trader should do (contract 1)."""

    schema_version: SchemaVersion
    kind: Literal["TradingProfile"]
    profile_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")]
    version: Annotated[int, Field(ge=1)]
    status: ProfileStatus
    owner: Annotated[str, Field(min_length=1)]
    description: str | None = None
    status_history: list[StatusChange] | None = None
    objective: Objective
    capital: Capital
    risk_selection: RiskSelection
    universe: Universe
    horizon: Horizon
    execution: Execution
    explanations: Explanations
    data_sources: DataSources
