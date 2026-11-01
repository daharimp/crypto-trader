"""Compiled profile contract: the only configuration the engine reads."""

from __future__ import annotations

from typing import Any

from .common import DomainModel, SchemaVersion, VersionRef
from .enums import Environment, Provenance


class EffectiveValue(DomainModel):
    """A resolved configuration value with its provenance."""

    field: str
    value: Any
    provenance: Provenance
    ref: str
    source: str | None


class Blocker(DomainModel):
    """A required value that is still unresolved (fail closed, exit 3)."""

    field: str
    ref: str
    reason: str


class CompiledProfile(DomainModel):
    """Validated profile + risk profile + overlays for one environment."""

    schema_version: SchemaVersion
    environment: Environment
    trading_profile: VersionRef
    trading_profile_hash: str
    risk_profile: VersionRef
    risk_profile_hash: str
    eligibility_rules_hash: str
    asset_registry_hash: str
    experiment_id: str | None
    experiment_hash: str | None
    cost_scenario: dict[str, str]
    effective: dict[str, EffectiveValue]
    blockers: list[Blocker]
    errors: list[str]
    runnable: bool
    compiler_version: str
    live_authorization_hash: str | None = None
    config_hash: str
