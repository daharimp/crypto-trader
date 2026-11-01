"""T-07: unresolved values block the run; no defaults appear."""

from __future__ import annotations

from tests.conftest import EXP_2026_001, PROFILE
from trader.domain.enums import Environment, Provenance
from trader.profiles.blockers import required_fields
from trader.profiles.compiler import compile_profile, exit_code

EXPECTED = {"UD-01", "UD-02", "UD-03", "UD-04", "UD-12", "UD-15", "UD-16", "UD-17", "UD-18"}


def test_t07_shipped_profile_blocked() -> None:
    """T-07: exit 3 with the expected UD IDs and no defaults in effective."""
    c = compile_profile(PROFILE, Environment.BACKTEST)
    assert exit_code(c) == 3 and not c.runnable and not c.errors
    assert {b.ref for b in c.blockers} == EXPECTED
    assert all(b.reason == "RISK_CONFIG_UNRESOLVED" for b in c.blockers)
    # Only hypothesis values may be present without an experiment; nothing invented.
    assert {v.provenance for v in c.effective.values()} == {Provenance.HYPOTHESIS}
    for b in c.blockers:
        assert b.field not in c.effective


def test_paper_needs_more_fields() -> None:
    """Edge: paper adds UD-17 fault fields and UD-19."""
    backtest = set(required_fields(Environment.BACKTEST, {"core"}))
    paper = set(required_fields(Environment.PAPER, {"core"}))
    assert backtest < paper
    assert "risk.halt_and_liquidation.liquidation_policy_after_halt" in paper


def test_speculative_tier_adds_caps() -> None:
    """Edge: a speculative asset requires the speculative caps."""
    keys = required_fields(Environment.BACKTEST, {"core", "speculative"})
    assert "risk.concentration.speculative_total_cap_pct" in keys


def test_partial_experiment_still_blocked(fixture_experiment) -> None:  # type: ignore[no-untyped-def]
    """Failure: an experiment that omits a required value still blocks with its UD ID."""
    import yaml

    path = fixture_experiment()
    data = yaml.safe_load(path.read_text())
    del data["parameters"]["risk"]["sizing.risk_per_trade_pct"]
    path.write_text(yaml.safe_dump(data))
    c = compile_profile(PROFILE, Environment.BACKTEST, path)
    assert exit_code(c) == 3
    assert [b.ref for b in c.blockers] == ["UD-03"]
    assert compile_profile(PROFILE, Environment.BACKTEST, EXP_2026_001).runnable
