"""Asset registry, eligibility rules, and universe snapshot contracts (D-25, D-26)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from .common import DomainModel, SchemaVersion, UtcDatetime
from .params import GenericParam


class AssetEntry(DomainModel):
    """A registered asset and its tier."""

    asset_id: str
    name: str
    tier: Literal["core", "major", "speculative", "blocked"]
    tier_status: str
    aliases: list[str]
    blocked: bool


class InstrumentEntry(DomainModel):
    """A tradeable instrument definition."""

    instrument_id: str
    base: str
    quote: str
    type: str
    quantity_step: Decimal


class MarketMapping(DomainModel):
    """Venue symbol to canonical instrument mapping."""

    market_id: str
    venue_id: str
    venue_symbol: str
    instrument_id: str


class AssetRegistry(DomainModel):
    """``configs/universe/assets.yaml``."""

    schema_version: SchemaVersion
    kind: Literal["AssetRegistry"]
    version: int
    assets: list[AssetEntry]
    instruments: list[InstrumentEntry]
    market_symbol_map: list[MarketMapping]


class TierThresholds(DomainModel):
    """Threshold per tier."""

    core: GenericParam
    major: GenericParam
    speculative: GenericParam


class MinCriterion(DomainModel):
    """A minimum-threshold criterion."""

    metric: str
    min_by_tier: TierThresholds


class SpreadCriterion(DomainModel):
    """A maximum spread criterion."""

    metric: str
    max_by_tier: TierThresholds
    when_no_spread_data: GenericParam


class RuleCriterion(DomainModel):
    """A named qualitative rule."""

    rule: str


class EligibilityCriteria(DomainModel):
    """Eligibility criteria."""

    liquidity: MinCriterion
    data_history: MinCriterion
    spread: SpreadCriterion
    support: RuleCriterion
    explicit_exclusion: RuleCriterion


class TierAssignment(DomainModel):
    """Tier assignment rules (UD-06)."""

    core: Literal["owner_approved_only"]
    major: GenericParam
    speculative: GenericParam


class EligibilityRules(DomainModel):
    """``configs/universe/eligibility.yaml`` (thresholds UD-18)."""

    schema_version: SchemaVersion
    kind: Literal["EligibilityRules"]
    version: int
    criteria: EligibilityCriteria
    tier_assignment: TierAssignment


class CriterionOutcome(DomainModel):
    """Outcome of one eligibility criterion."""

    criterion: str
    passed: bool
    observed: str | None
    threshold: str | None
    reason: str | None


class AssetEligibility(DomainModel):
    """Point-in-time eligibility of one instrument."""

    instrument_id: str
    asset_id: str
    tier: str
    eligible: bool
    criteria: list[CriterionOutcome]
    reason: str | None


class UniverseSnapshot(DomainModel):
    """Eligibility of every in-scope instrument at time ``as_of_utc``."""

    schema_version: SchemaVersion
    universe_snapshot_id: str
    as_of_utc: UtcDatetime
    assets: dict[str, AssetEligibility]
