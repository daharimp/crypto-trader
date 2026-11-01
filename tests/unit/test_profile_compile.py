"""T-01 and T-10: compiling the shipped profile with EXP-2026-001."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from tests.conftest import EXP_2026_001, PROFILE, dump, load
from trader.domain.enums import Environment, Provenance
from trader.profiles.compiler import compile_bundle, compile_profile, exit_code


def test_t01_balanced_compiles_with_experiment() -> None:
    """T-01: runnable; capital 2500; funds simulated; balanced; config_hash."""
    b = compile_bundle(PROFILE, Environment.BACKTEST, EXP_2026_001)
    c = b.compiled
    assert c.runnable and exit_code(c) == 0
    assert b.profile is not None and b.profile.capital.paper_capital_usd == Decimal("2500")
    assert b.profile.capital.funds == "simulated"
    assert c.risk_profile.id == "balanced"
    assert c.config_hash.startswith("sha256:")
    assert c.experiment_id == "EXP-2026-001"


def test_t10_hash_deterministic_and_provenance() -> None:
    """T-10: same inputs -> same hash; provenance labels correct."""
    a = compile_profile(PROFILE, Environment.BACKTEST, EXP_2026_001)
    b = compile_profile(PROFILE, Environment.BACKTEST, EXP_2026_001)
    assert a.config_hash == b.config_hash
    core = a.effective["risk.concentration.core_per_asset_cap_pct"]
    assert core.provenance == Provenance.HYPOTHESIS and core.ref == "H-01"
    for ref in ("H-01", "H-02", "H-03", "H-04"):
        assert any(
            v.ref == ref and v.provenance == Provenance.HYPOTHESIS for v in a.effective.values()
        )
    daily = a.effective["risk.limits.daily_loss_limit_pct"]
    assert daily.provenance == Provenance.EXPERIMENT and daily.ref == "UD-02"


def test_t10_changing_an_input_changes_hash(tmp_path: Path) -> None:
    """T-10: a different experiment value changes config_hash."""
    base = compile_profile(PROFILE, Environment.BACKTEST, EXP_2026_001)
    data = load(EXP_2026_001)
    data["parameters"]["risk"]["limits.daily_loss_limit_pct"]["value"] = 2
    other = dump(tmp_path / "EXP-2026-001.yaml", data)
    changed = compile_profile(PROFILE, Environment.BACKTEST, other)
    assert changed.runnable and changed.config_hash != base.config_hash


def test_cost_scenario_and_environment_change_hash() -> None:
    """Edge: environment and cost scenario are part of the hash."""
    base = compile_bundle(PROFILE, Environment.BACKTEST, EXP_2026_001).compiled
    stress = compile_bundle(PROFILE, Environment.BACKTEST, EXP_2026_001, cost_scenario="stress")
    assert stress.compiled.cost_scenario["fee_rate_pct"] == "0.60"
    assert stress.compiled.config_hash != base.config_hash


def test_missing_cost_scenario_is_error() -> None:
    """Failure: unknown cost scenario is a schema error (exit 2)."""
    c = compile_bundle(PROFILE, Environment.BACKTEST, EXP_2026_001, cost_scenario="nope").compiled
    assert exit_code(c) == 2
