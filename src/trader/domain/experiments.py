"""Experiment definition and record contracts (contract 13, ADR-016)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from .common import DomainModel, SchemaVersion, VersionRef

ExperimentId = Annotated[str, Field(pattern=r"^EXP-\d{4}-\d{3}$")]


class ExperimentParam(DomainModel):
    """One labelled, non-approved value supplied for a research backtest."""

    value: Any
    source: str


class ExperimentParameters(DomainModel):
    """Parameter overlays by namespace (dotted field paths)."""

    risk: dict[str, ExperimentParam] = Field(default_factory=dict)
    eligibility: dict[str, ExperimentParam] = Field(default_factory=dict)


class ExperimentStrategy(DomainModel):
    """Strategy under test."""

    strategy_id: str
    version: str


class ExperimentDefinition(DomainModel):
    """``experiments/EXP-*.yaml``. Accepted only in the backtest environment."""

    schema_version: SchemaVersion
    kind: Literal["ExperimentDefinition"]
    experiment_id: ExperimentId
    title: str
    purpose: str
    hypothesis: str
    environment: Literal["backtest"]
    trading_profile: str
    strategy: ExperimentStrategy
    timeframe: Literal["1h", "4h"]
    cost_scenario: str
    parameters: ExperimentParameters


class ExperimentRecord(DomainModel):
    """Machine-readable record of one experiment run."""

    schema_version: SchemaVersion
    experiment_id: ExperimentId
    title: str
    hypothesis: str
    purpose: str
    status: str
    data: dict[str, Any]
    strategy: VersionRef
    profile_refs: dict[str, str]
    experiment_parameters: list[dict[str, str]]
    assumptions: dict[str, str]
    method: dict[str, Any]
    results: dict[str, Any]
    overfit_checks: dict[str, str]
    failure_analysis: str | None
    decision: dict[str, str] | None
    reproduction: dict[str, str]
    run_ids: list[str]
