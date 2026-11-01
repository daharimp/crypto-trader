"""T-08 and T-09: experiment parameters are research-only and cannot touch protected values."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import EXP_2026_001, PROFILE, dump, load
from trader.domain.enums import Environment
from trader.profiles.compiler import compile_profile, exit_code


def test_t08_experiment_refused_in_paper() -> None:
    """T-08: EXP-2026-001 with paper -> EXPERIMENT_PARAMETERS_REJECTED."""
    c = compile_profile(PROFILE, Environment.PAPER, EXP_2026_001)
    assert any(e.startswith("EXPERIMENT_PARAMETERS_REJECTED") for e in c.errors)
    assert exit_code(c) == 2


@pytest.mark.parametrize(
    "path",
    [
        "global_hard_constraints.leverage_allowed",
        "kill_switch.manual_disengage",
        "halt_and_liquidation.liquidation_policy_after_halt",
        "loss_response.hard_thresholds_override_all",
        "limits.no_such_field",
    ],
)
def test_t09_protected_fields(path: str, fixture_experiment: Any) -> None:
    """T-09: protected sections and non-parameters cannot be overridden."""
    c = compile_profile(PROFILE, Environment.BACKTEST, fixture_experiment({path: True}))
    assert any(e.startswith("EXPERIMENT_PARAMETERS_REJECTED") and path in e for e in c.errors)
    assert not c.runnable


def test_t09_approved_field_cannot_be_overridden(
    configs_copy: Path, fixture_experiment: Any
) -> None:
    """T-09: a field already approved (fixture risk file) cannot be overridden."""
    rp = configs_copy / "risk" / "balanced.yaml"
    data = load(rp)
    data["limits"]["daily_loss_limit_pct"] = {
        "value": 3,
        "status": "approved",
        "ref": "D-12",
        "approved_by": "fixture-owner",
        "approved_on": "2026-10-01",
    }
    dump(rp, data)
    exp = fixture_experiment({"limits.daily_loss_limit_pct": 2})
    c = compile_profile(PROFILE, Environment.BACKTEST, exp, configs_root=configs_copy)
    assert any("is approved" in e for e in c.errors)
    eff = c.effective["risk.limits.daily_loss_limit_pct"]
    assert eff.provenance.value == "approved" and eff.value == 3


def test_hypothesis_field_can_be_overridden(fixture_experiment: Any) -> None:
    """Edge: hypothesis fields may be tested with experiment values."""
    c = compile_profile(
        PROFILE,
        Environment.BACKTEST,
        fixture_experiment({"concentration.core_per_asset_cap_pct": 25}),
    )
    assert c.runnable
    ev = c.effective["risk.concentration.core_per_asset_cap_pct"]
    assert ev.value == 25 and ev.provenance.value == "fixture" and ev.ref == "H-01"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("limits.daily_loss_limit_pct", 150),
        ("limits.daily_loss_limit_pct", "TBD"),
        ("allocation.max_open_positions", 0),
        ("sizing.hard_stop_policy", {"method": "atr_multiple"}),
    ],
)
def test_out_of_range_values_rejected(path: str, value: Any, fixture_experiment: Any) -> None:
    """Failure: values must satisfy the parameter's schema."""
    c = compile_profile(PROFILE, Environment.BACKTEST, fixture_experiment({path: value}))
    assert any(e.startswith("EXPERIMENT_PARAMETERS_REJECTED") for e in c.errors)
