"""Experiment run records (``data/experiments/<id>/runs/<run_id>.json``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trader.common.paths import data_root
from trader.domain.common import VersionRef
from trader.domain.compiled import CompiledProfile
from trader.domain.experiments import ExperimentDefinition, ExperimentRecord


def write_run_record(
    exp: ExperimentDefinition,
    compiled: CompiledProfile,
    run_id: str,
    data: dict[str, Any],
    results: dict[str, Any],
    command: str,
) -> Path:
    """
    Write an ExperimentRecord for one completed run.

    Args:
        exp (ExperimentDefinition): Experiment.
        compiled (CompiledProfile): Compiled profile used.
        run_id (str): Run ID.
        data (dict[str, Any]): Data section (datasets, window).
        results (dict[str, Any]): Headline results.
        command (str): Reproduction command.

    Returns:
        Path: Record path.
    """
    params = [
        {
            "field": k,
            "value": json.dumps(str(v.value)),
            "source": v.source or "",
            "provenance": v.provenance.value,
        }
        for k, v in sorted(compiled.effective.items())
        if v.provenance.value in ("experiment", "fixture")
    ]
    rec = ExperimentRecord(
        schema_version="1.0.0",
        experiment_id=exp.experiment_id,
        title=exp.title,
        hypothesis=exp.hypothesis,
        purpose=exp.purpose,
        status="completed",
        data=data,
        strategy=VersionRef(id=exp.strategy.strategy_id, version=exp.strategy.version),
        profile_refs={
            "trading_profile": compiled.trading_profile.id,
            "trading_profile_version": compiled.trading_profile.version,
            "risk_profile": compiled.risk_profile.id,
            "config_hash": compiled.config_hash,
        },
        experiment_parameters=params,
        assumptions={
            "costs": compiled.cost_scenario.get("scenario_id", ""),
            "fills": "next_bar_open with slippage; no partial fills",
        },
        method={"type": "single_backtest", "environment": "backtest"},
        results=results,
        overfit_checks={"status": "not_evaluated_in_M1"},
        failure_analysis=None,
        decision=None,
        reproduction={"command": command, "config_hash": compiled.config_hash},
        run_ids=[run_id],
    )
    out = data_root() / "experiments" / exp.experiment_id / "runs" / f"{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rec.model_dump_json(indent=2))
    return out
