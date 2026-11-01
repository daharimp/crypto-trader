"""T-04, T-05, T-06: policy rules PV-01..PV-10 and RP-01..RP-06."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import EXP_2026_001, PROFILE, dump, load
from trader.domain.enums import Environment
from trader.profiles.compiler import compile_profile, exit_code


def _compile(
    tmp_path: Path,
    data: dict[str, Any],
    env: Environment = Environment.BACKTEST,
    exp: Path | None = EXP_2026_001,
    **kw: Any,
):
    return compile_profile(dump(tmp_path / "p.yaml", data), env, exp, **kw)


def test_t04_aggressive_without_ack(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """T-04: aggressive without acknowledgement."""
    profile_data["risk_selection"]["risk_profile_id"] = "aggressive"
    c = _compile(tmp_path, profile_data, exp=None)
    assert any(e.startswith("AGGRESSIVE_NOT_ACKNOWLEDGED") for e in c.errors)
    assert exit_code(c) == 2


def test_aggressive_with_ack_passes_policy(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """Edge: an acknowledged aggressive selection passes PV-03 (values still blocked)."""
    profile_data["risk_selection"]["risk_profile_id"] = "aggressive"
    profile_data["risk_selection"]["aggressive_acknowledgement"] = {
        "acknowledged": True,
        "acknowledged_by": "owner",
        "acknowledged_at_utc": "2026-10-01T00:00:00Z",
        "statement": "I explicitly select the Aggressive profile.",
    }
    c = _compile(tmp_path, profile_data, exp=None)
    assert not any("AGGRESSIVE" in e for e in c.errors)
    assert exit_code(c) == 3  # Aggressive values are TBD (UD-13)
    assert any(b.ref == "UD-13" for b in c.blockers)


@pytest.mark.parametrize("status", ["draft", "suspended"])
def test_t05_draft_suspended_cannot_run(
    status: str, profile_data: dict[str, Any], tmp_path: Path
) -> None:
    """T-05: draft and suspended -> PROFILE_NOT_RUNNABLE."""
    profile_data["status"] = status
    c = _compile(tmp_path, profile_data)
    assert any(e.startswith("PROFILE_NOT_RUNNABLE") for e in c.errors)
    assert not c.runnable


def test_t05_validated_cannot_run_paper() -> None:
    """T-05: validated cannot run paper."""
    c = compile_profile(PROFILE, Environment.PAPER)
    assert any(e.startswith("PROFILE_NOT_RUNNABLE") for e in c.errors)


def test_active_paper_still_needs_activation(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """Edge: active status without an activation record is still not runnable in paper."""
    profile_data["status"] = "active"
    c = _compile(tmp_path, profile_data, env=Environment.PAPER, exp=None)
    assert any("activation record" in e for e in c.errors)


def test_environment_not_permitted(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """Failure: backtest not in permitted_environments."""
    profile_data["execution"]["permitted_environments"] = ["paper"]
    c = _compile(tmp_path, profile_data)
    assert any("PV-08" in e for e in c.errors)


def test_t06_pv01_disallowed_core(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """T-06: BTC both Core and disallowed."""
    profile_data["universe"]["disallowed_assets"] = ["BTC"]
    c = _compile(tmp_path, profile_data)
    assert any(e.startswith("PROFILE_CONTRADICTION [PV-01]") for e in c.errors)


def test_t06_pv02_instrument_outside_core(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """T-06: SOL-USD not in Core or allowlist."""
    profile_data["universe"]["instruments_in_scope"].append("SOL-USD")
    c = _compile(tmp_path, profile_data)
    assert any(e.startswith("PROFILE_CONTRADICTION [PV-02]") for e in c.errors)


def test_pv09_core_needs_core_tier(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """PV-09: core assets require the core tier."""
    profile_data["universe"]["allowed_tiers"] = ["major"]
    c = _compile(tmp_path, profile_data)
    assert any("PV-09" in e for e in c.errors)


def test_pv05_intraday_not_approved(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """PV-05: intraday enabled while UD-14 is unresolved."""
    profile_data["horizon"]["minute_data"]["intraday_strategies_enabled"] = True
    c = _compile(tmp_path, profile_data)
    assert any(e.startswith("INTRADAY_NOT_APPROVED") for e in c.errors)


def test_pv06_refinement_without_source(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """PV-06: refinement enabled without a 1m source."""
    profile_data["horizon"]["minute_data"]["entry_exit_refinement_enabled"] = True
    c = _compile(tmp_path, profile_data)
    assert any("PV-06" in e for e in c.errors)


def test_pv07_non_v1_source_required(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """PV-07: a V1.5 source required for trading."""
    profile_data["data_sources"]["active"].append(
        {"source_id": "order_book", "tier": "V1.5", "required_for_trading": True}
    )
    c = _compile(tmp_path, profile_data)
    assert any(e.startswith("DATA_SOURCE_NOT_PERMITTED") for e in c.errors)


def test_pv04_risk_version_mismatch(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """PV-04: requested risk version does not exist."""
    profile_data["risk_selection"]["risk_profile_version"] = 2
    c = _compile(tmp_path, profile_data)
    assert any(e.startswith("RISK_PROFILE_NOT_FOUND") for e in c.errors)


def test_pv04_risk_file_missing(
    profile_data: dict[str, Any], configs_copy: Path, tmp_path: Path
) -> None:
    """PV-04: risk profile file missing."""
    (configs_copy / "risk" / "balanced.yaml").unlink()
    c = _compile(tmp_path, profile_data, configs_root=configs_copy)
    assert any(e.startswith("RISK_PROFILE_NOT_FOUND") for e in c.errors)


def test_pv10_version_not_incremented(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """PV-10: same id+version with different content is rejected."""
    assert compile_profile(PROFILE, Environment.BACKTEST, EXP_2026_001).runnable
    profile_data["description"] = "edited without a version bump"
    c = _compile(tmp_path, profile_data)
    assert any(e.startswith("PROFILE_VERSION_NOT_INCREMENTED") for e in c.errors)
    profile_data["version"] = 2
    assert _compile(tmp_path, profile_data).runnable


@pytest.mark.parametrize(
    ("risk", "rule"),
    [
        (
            {
                "allocation.total_exposure_cap_pct": 90,
                "allocation.minimum_reserve_pct_range": {"low": 20, "high": 40},
            },
            "RP-01",
        ),
        (
            {
                "limits.daily_loss_limit_pct": 20,
                "limits.portfolio_drawdown_circuit_breaker_pct": 15,
            },
            "RP-04",
        ),
        ({"sizing.risk_per_trade_pct": 3}, "RP-05"),
        ({"allocation.minimum_reserve_pct_range": {"low": 40, "high": 20}}, "RP-06"),
        ({"allocation.total_exposure_cap_pct": 30}, "RP-02"),
    ],
)
def test_t06_risk_contradictions(risk: dict[str, Any], rule: str, fixture_experiment: Any) -> None:
    """T-06: RP-01, RP-02, RP-04, RP-05, RP-06 contradictions."""
    c = compile_profile(PROFILE, Environment.BACKTEST, fixture_experiment(risk))
    assert any(e.startswith(f"RISK_PROFILE_CONTRADICTION [{rule}]") for e in c.errors), c.errors
    assert exit_code(c) == 2


def test_fixture_provenance(fixture_experiment: Any) -> None:
    """Fixture experiments are labelled fixture, never experiment."""
    c = compile_profile(PROFILE, Environment.BACKTEST, fixture_experiment())
    assert c.runnable
    assert c.effective["risk.limits.daily_loss_limit_pct"].provenance.value == "fixture"


def test_fixture_id_outside_fixtures_rejected(tmp_path: Path) -> None:
    """Failure: EXP-0000 IDs are reserved for tests/fixtures."""
    data = load(EXP_2026_001)
    data["experiment_id"] = "EXP-0000-777"
    c = compile_profile(PROFILE, Environment.BACKTEST, dump(tmp_path / "x.yaml", data))
    assert any(e.startswith("EXPERIMENT_PARAMETERS_REJECTED") for e in c.errors)
