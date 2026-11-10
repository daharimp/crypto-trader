"""Owner decisions of 2026-11-01 applied to the shipped configs (product-requirements §10.2)."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import EXP_2026_001, SHIPPED_CONFIGS, SHIPPED_PROFILE, dump, load
from trader.domain.enums import Environment, Provenance
from trader.profiles.compiler import compile_bundle, exit_code

D = Decimal
# Option values chosen by the owner, per profile (Conservative / Balanced / Aggressive).
EXPECTED: dict[str, dict[str, Any]] = {
    "conservative": {
        "breaker": 10,
        "daily": 2,
        "rpt": "0.5",
        "res": (30, 60),
        "exp": 50,
        "pos": 3,
        "cd": (2, 48),
        "caps": (25, 10, "2.5", 5),
    },
    "balanced": {
        "breaker": 15,
        "daily": 3,
        "rpt": "1.0",
        "res": (20, 40),
        "exp": 80,
        "pos": 5,
        "cd": (3, 24),
        "caps": (35, 15, 5, 10),
    },
    "aggressive": {
        "breaker": 25,
        "daily": 5,
        "rpt": "1.5",
        "res": (10, 25),
        "exp": 90,
        "pos": 8,
        "cd": (4, 12),
        "caps": (45, 20, "7.5", 15),
    },
}


def _profile_for(risk_id: str, tmp_path: Path) -> Path:
    """The shipped profile, re-pointed at another risk profile (with acknowledgement)."""
    data = load(SHIPPED_PROFILE)
    data["profile_id"] = f"{risk_id}-check"
    data["risk_selection"]["risk_profile_id"] = risk_id
    data["risk_selection"]["risk_profile_version"] = load(
        SHIPPED_CONFIGS / "risk" / f"{risk_id}.yaml"
    )["version"]
    if risk_id == "aggressive":
        data["risk_selection"]["aggressive_acknowledgement"] = {
            "acknowledged": True,
            "acknowledged_by": "test",
            "statement": "Explicit selection of the Aggressive profile for a test.",
            "acknowledged_at_utc": "2026-11-01T00:00:00Z",
        }
    return dump(tmp_path / f"{risk_id}.yaml", data)


def _compile(profile: Path, env: Environment = Environment.BACKTEST, exp: Path | None = None):  # type: ignore[no-untyped-def]
    return compile_bundle(profile, env, exp, SHIPPED_CONFIGS).compiled


def test_shipped_backtest_runnable_without_experiment() -> None:
    """Expected: no blockers; only approved values plus the Balanced hypotheses H-01..H-04."""
    c = _compile(SHIPPED_PROFILE)
    assert c.runnable and exit_code(c) == 0 and not c.blockers
    hyp = {v.ref for v in c.effective.values() if v.provenance == Provenance.HYPOTHESIS}
    assert hyp == {"H-01", "H-02", "H-03", "H-04"}
    assert {v.provenance for v in c.effective.values()} == {
        Provenance.APPROVED,
        Provenance.HYPOTHESIS,
    }


@pytest.mark.parametrize("risk_id", ["conservative", "balanced", "aggressive"])
def test_approved_values_match_decisions(risk_id: str, tmp_path: Path) -> None:
    """Each profile compiles cleanly with exactly the approved option values."""
    c = _compile(SHIPPED_PROFILE if risk_id == "balanced" else _profile_for(risk_id, tmp_path))
    assert c.runnable, (c.errors, c.blockers)
    e, x = c.effective, EXPECTED[risk_id]

    def val(k: str) -> Any:
        return e[f"risk.{k}"].value

    assert val("limits.portfolio_drawdown_circuit_breaker_pct") == D(x["breaker"])
    assert val("limits.daily_loss_limit_pct") == D(x["daily"])
    assert val("sizing.risk_per_trade_pct") == D(x["rpt"])
    assert val("allocation.minimum_reserve_pct_range") == {
        "low": D(x["res"][0]),
        "high": D(x["res"][1]),
    }
    assert val("allocation.total_exposure_cap_pct") == D(x["exp"])
    assert val("allocation.max_open_positions") == x["pos"]
    assert val("cooldown.after_consecutive_losing_trades.count") == x["cd"][0]
    assert val("cooldown.after_consecutive_losing_trades.duration_hours") == D(x["cd"][1])
    caps = [
        val(f"concentration.{t}")
        for t in (
            "core_per_asset_cap_pct",
            "major_per_asset_cap_pct",
            "speculative_per_asset_cap_pct",
            "speculative_total_cap_pct",
        )
    ]
    assert caps == [D(str(v)) for v in x["caps"]]
    assert val("sizing.hard_stop_policy") == {
        "method": "atr_multiple",
        "timeframe": "decision_timeframe",
        "atr_period_bars": 14,
        "atr_multiple": D("2.0"),
    }
    assert val("loss_response.size_reduction_schedule")["method"] == (
        "stepwise_fraction_of_breaker"
    )
    assert val("sizing.adaptation.upward_multiplier_max") == 1
    assert val("halt_and_liquidation.liquidation_policy_after_halt") == (
        "hold_with_owner_flatten_command"
    )
    assert (
        val("data_and_execution_faults.exchange_errors.max_consecutive_errors_before_kill_switch")
        == 3
    )
    assert val("data_and_execution_faults.stale_data.paper_grace_seconds") == 120
    assert val("data_and_execution_faults.clock_skew_tolerance_seconds") == 5


def test_rp08_profile_ordering() -> None:
    """RP-08: conservative <= balanced <= aggressive (reserve floor in reverse)."""

    def num(rid: str, key: str) -> Decimal:
        return D(
            str(
                EXPECTED[rid][key]
                if not isinstance(EXPECTED[rid][key], tuple)
                else EXPECTED[rid][key][0]
            )
        )

    for key in ("breaker", "daily", "rpt", "exp"):
        assert num("conservative", key) <= num("balanced", key) <= num("aggressive", key)
    assert num("conservative", "res") >= num("balanced", "res") >= num("aggressive", "res")


def test_every_approved_value_has_approver_and_date() -> None:
    """Approved values record who approved them and when (decision dates 11-01..11-03)."""
    for f in [
        *(SHIPPED_CONFIGS / "risk").glob("*.yaml"),
        SHIPPED_CONFIGS / "universe" / "eligibility.yaml",
    ]:
        for line in f.read_text().splitlines():
            if "status: approved" in line:
                assert "approved_by: Dahari Morgan-Parker" in line
                assert re.search(r'approved_on: "2026-11-0[123]"', line), line
            if "TBD" in line and not line.lstrip().startswith("#"):
                assert "UD-14" in line, (f.name, line)


def test_paper_has_no_blockers_but_needs_activation() -> None:
    """Paper: all required values resolved; refused until an activation record exists."""
    c = _compile(SHIPPED_PROFILE, Environment.PAPER)
    assert not c.blockers and exit_code(c) == 2
    assert len(c.errors) == 1
    assert c.errors[0].startswith("PROFILE_NOT_RUNNABLE [PV-08]: paper requires an activation")


def test_experiment_cannot_override_approved_values() -> None:
    """Failure: EXP-2026-001 targets now-approved fields and is rejected (RP-12)."""
    c = _compile(SHIPPED_PROFILE, exp=EXP_2026_001)
    assert not c.runnable and exit_code(c) == 2
    assert all(e.startswith("EXPERIMENT_PARAMETERS_REJECTED") for e in c.errors)
    assert len(c.errors) == 14


def test_aggressive_still_requires_acknowledgement(tmp_path: Path) -> None:
    """Edge: approving Aggressive values does not remove the D-06 acknowledgement rule."""
    data = load(_profile_for("aggressive", tmp_path))
    del data["risk_selection"]["aggressive_acknowledgement"]
    c = _compile(dump(tmp_path / "agg.yaml", data))
    assert any(e.startswith("AGGRESSIVE_NOT_ACKNOWLEDGED") for e in c.errors)


def test_intraday_still_disabled() -> None:
    """UD-14 deferred: enabling intraday strategies is still refused (PV-05)."""
    import tempfile

    data = load(SHIPPED_PROFILE)
    data["horizon"]["minute_data"]["intraday_strategies_enabled"] = True
    with tempfile.TemporaryDirectory() as d:
        c = _compile(dump(Path(d) / "p.yaml", data))
    assert any(e.startswith("INTRADAY_NOT_APPROVED") for e in c.errors)


def test_aggressive_intraday_sleeve_values_approved(tmp_path: Path) -> None:
    """UD-14 revisit (2026-11-03): Aggressive sleeve 10% cap, 2.5% daily, 12.5% breaker."""
    e = _compile(_profile_for("aggressive", tmp_path)).effective
    assert e["risk.allocation.intraday_allocation_cap_pct"].value == D(10)
    sleeve = "risk.allocation.intraday_sleeve_limits"
    assert e[f"{sleeve}.daily_loss_limit_pct"].value == D("2.5")
    assert e[f"{sleeve}.drawdown_circuit_breaker_pct"].value == D("12.5")


def test_intraday_still_disabled_in_shipped_profile() -> None:
    """Edge: approved sleeve values do not enable intraday; the profile flag stays off."""
    assert load(SHIPPED_PROFILE)["horizon"]["minute_data"]["intraday_strategies_enabled"] is False


def test_balanced_intraday_stays_unresolved() -> None:
    """Failure guard: only Aggressive got sleeve values; Balanced remains TBD (fail closed)."""
    risk = load(SHIPPED_CONFIGS / "risk" / "balanced.yaml")
    assert risk["allocation"]["intraday_allocation_cap_pct"]["value"] == "TBD"
