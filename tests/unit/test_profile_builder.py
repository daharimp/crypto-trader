"""Profile builder (ADR-024): question bank, answer checks, rendering, compile, CLI."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS, dump, load
from trader.cli.main import app
from trader.cli.profile_build import interview
from trader.domain.enums import Environment
from trader.profiles.builder import BuildError, build, check_answer, validate_answers
from trader.profiles.compiler import compile_bundle
from trader.profiles.questions import PRESETS, bank_json, questions_for

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
ACK = "I choose this profile and accept that I can lose money."


def _answers(**over: Any) -> dict[str, Any]:
    """A complete Aggressive-preset answer set."""
    a: dict[str, Any] = {
        "owner": "Test Owner",
        "profile_id": "swing-aggressive",
        "preset": "aggressive",
        "decision_timeframe": "4h",
        "strategy_id": "sma_trend",
        "coins": ["BTC", "ETH", "SOL", "XRP", "SUI"],
        "paper_capital_usd": 2500,
        "breaker_pct": 25,
        "daily_loss_pct": 5,
        "risk_per_trade_pct": 1.5,
        "exposure_pct": 90,
        "max_positions": 8,
        "stop_atr_multiple": 2.0,
        "reserve_pct_range": [10, 25],
        "core_cap_pct": 45,
        "major_cap_pct": 20,
        "spec_cap_pct": 7.5,
        "spec_total_pct": 15,
        "cooldown": "A",
        "intraday_cap_pct": 10,
        "intraday_limits": "B",
        "max_exchange_errors": 3,
        "stale_grace_seconds": 120,
        "stale_cycles": 3,
        "clock_skew_seconds": 5,
        "acknowledgement": ACK,
    }
    a.update(over)
    return a


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A writable copy of the shipped configs."""
    r = tmp_path / "configs"
    shutil.copytree(SHIPPED_CONFIGS, r)
    return r


def _eff(root: Path, pid: str) -> dict[str, Any]:
    c = compile_bundle(root / "profiles" / f"{pid}.yaml", Environment.BACKTEST, None, root).compiled
    assert c.runnable, c.errors
    return {k: v.value for k, v in c.effective.items()}


def test_build_writes_compilable_profile_with_answers(root: Path, tmp_path: Path) -> None:
    """Expected: files written; compiled values equal the answers; sleeve = half limits."""
    res = build(_answers(), root, tmp_path / "docs", now=NOW)
    assert res.errors == [] and res.exit_code == 0 and res.spec_path.exists()
    e = _eff(root, "swing-aggressive")
    assert e["risk.limits.portfolio_drawdown_circuit_breaker_pct"] == D(25)
    assert e["risk.sizing.risk_per_trade_pct"] == D("1.5")
    assert e["risk.allocation.intraday_allocation_cap_pct"] == D(10)
    assert e["risk.allocation.intraday_sleeve_limits.daily_loss_limit_pct"] == D("2.5")
    assert e["risk.allocation.intraday_sleeve_limits.drawdown_circuit_breaker_pct"] == D("12.5")
    prof = load(res.profile_path)
    assert prof["trading_spec"] == {
        "strategy_id": "sma_trend",
        "decision_timeframe": "4h",
        "built_with": "profile_builder",
    }
    assert prof["risk_selection"]["aggressive_acknowledgement"]["statement"] == ACK
    risk = load(res.risk_path)
    assert risk["selection"]["explicit_selection_required"] is True
    assert risk["limits"]["daily_loss_limit_pct"]["approved_by"] == "Test Owner"
    assert "Test Owner" in res.spec_path.read_text()


def test_custom_value_inside_envelope_and_intraday_off(root: Path, tmp_path: Path) -> None:
    """Edge: a typed value inside the spec range is kept; slice off keeps UD-14 TBD."""
    a = _answers(profile_id="custom-one", risk_per_trade_pct="1.8", intraday_cap_pct=0)
    res = build(a, root, tmp_path / "docs", now=NOW)
    assert res.errors == []
    e = _eff(root, "custom-one")
    assert e["risk.sizing.risk_per_trade_pct"] == D("1.8")
    assert load(res.risk_path)["allocation"]["intraday_allocation_cap_pct"]["value"] == "TBD"


@pytest.mark.parametrize(
    ("over", "msg"),
    [
        ({"risk_per_trade_pct": 5}, "outside the spec's range"),
        ({"breaker_pct": 40}, "outside the spec's range"),
        ({"max_positions": "4.5"}, "whole number"),
        ({"profile_id": "aggressive"}, "reserved"),
        ({"profile_id": "Bad Name"}, "does not match"),
        ({"acknowledgement": "ok"}, "at least 20"),
        ({"coins": ["DOGE"]}, "choose one or more"),
        ({"max_exchange_errors": 4}, "is not one of"),
        ({"strategy_id": "random_entry"}, "is not one of"),
        ({"decision_timeframe": "1h", "strategy_id": "volatility_breakout"}, "does not support"),
    ],
)
def test_invalid_answers_refused(root: Path, over: dict[str, Any], msg: str) -> None:
    """Failure: values outside the spec, reserved names, controls, and bad text are refused."""
    with pytest.raises(BuildError, match=msg):
        validate_answers(_answers(**over), root)


def test_contradictory_answers_fail_compile_and_write_nothing(root: Path, tmp_path: Path) -> None:
    """Failure: exposure 95% + reserve floor 20% > 100% (RP-01) is not written."""
    a = _answers(profile_id="too-much", exposure_pct=95, reserve_pct_range=[20, 40])
    res = build(a, root, tmp_path / "docs", now=NOW)
    assert res.errors and not res.profile_path.exists() and not res.risk_path.exists()


def test_existing_profile_needs_update_and_increments(root: Path, tmp_path: Path) -> None:
    """Edge: rebuilding refuses silent overwrite; --update writes version 2."""
    build(_answers(), root, tmp_path / "docs", now=NOW)
    with pytest.raises(BuildError, match="--update"):
        build(_answers(), root, tmp_path / "docs", now=NOW)
    res = build(_answers(breaker_pct=20), root, tmp_path / "docs", update=True, now=NOW)
    assert load(res.profile_path)["version"] == 2 and load(res.risk_path)["version"] == 2
    assert load(res.profile_path)["risk_selection"]["risk_profile_version"] == 2


def test_dry_run_writes_nothing(root: Path, tmp_path: Path) -> None:
    """Edge: --dry-run compiles but writes no file."""
    res = build(_answers(), root, tmp_path / "docs", dry_run=True, now=NOW)
    assert res.exit_code == 0 and not res.profile_path.exists()


def test_explicit_selection_profile_without_ack_is_refused(root: Path, tmp_path: Path) -> None:
    """Failure (PV-03 generalized): removing the acknowledgement makes the profile invalid."""
    res = build(_answers(), root, tmp_path / "docs", now=NOW)
    data = load(res.profile_path)
    del data["risk_selection"]["aggressive_acknowledgement"]
    data["version"] = 9
    c = compile_bundle(dump(res.profile_path, data), Environment.BACKTEST, None, root).compiled
    assert any(e.startswith("AGGRESSIVE_NOT_ACKNOWLEDGED") for e in c.errors)


def test_risk_file_must_declare_its_own_id(root: Path, tmp_path: Path) -> None:
    """Failure: configs/risk/<id>.yaml declaring another ID is refused (PV-04)."""
    res = build(_answers(), root, tmp_path / "docs", now=NOW)
    risk = load(res.risk_path)
    risk["risk_profile_id"] = "someone-else"
    dump(res.risk_path, risk)
    c = compile_bundle(res.profile_path, Environment.BACKTEST, None, root).compiled
    assert any("declares 'someone-else'" in e for e in c.errors)


def test_bank_offers_preset_columns_and_envelopes() -> None:
    """Expected: each preset offers its own spec column; custom range spans all presets."""
    strategies = [{"id": "sma_trend", "timeframes": ["1h", "4h"]}]
    qs = {p: {q.id: q for q in questions_for(p, strategies, ["BTC"])} for p in PRESETS}
    assert [o.value for o in qs["conservative"]["breaker_pct"].options] == [8, 10, 12]
    assert [o.value for o in qs["aggressive"]["breaker_pct"].options] == [20, 25, 30]
    assert qs["balanced"]["breaker_pct"].custom_min == 8
    assert qs["balanced"]["breaker_pct"].custom_max == 30
    assert len(qs["balanced"]["cooldown"].options) == 1
    bank = bank_json(strategies, ["BTC"])
    assert set(bank["presets"]) == set(PRESETS) and bank["header"][0]["id"] == "owner"
    json.dumps(bank, default=str)
    with pytest.raises(ValueError):
        questions_for("yolo", strategies, ["BTC"])


def test_check_answer_option_key_and_range() -> None:
    """Edge: option keys map to values; a custom reserve range must be ordered."""
    qs = {
        q.id: q for q in questions_for("balanced", [{"id": "x_y", "timeframes": ["4h"]}], ["BTC"])
    }
    assert check_answer(qs["cooldown"], "A") == [3, 24]
    assert check_answer(qs["reserve_pct_range"], [15, 35]) == [D(15), D(35)]
    with pytest.raises(BuildError):
        check_answer(qs["reserve_pct_range"], [40, 20])


def test_terminal_interview_with_defaults_and_a_retry(root: Path) -> None:
    """Expected: Enter takes the recommended option; a bad answer is re-asked."""
    # owner, name, preset (Enter), timeframe, strategy, coins, capital (Enter),
    # breaker "99" (refused) then Enter, 16 more Enters (slice off skips its limits), sign-off.
    lines = iter(
        ["Test Owner", "quick-1h", "", "1h", "mean_reversion", "BTC,ETH", "", "99", ""]
        + [""] * 16
        + [ACK]
    )
    out: list[str] = []

    def asker(_prompt: str) -> str:
        return next(lines)

    a = interview(root, asker, out.append)
    assert a["preset"] == "balanced" and a["decision_timeframe"] == "1h"
    assert a["coins"] == ["BTC", "ETH"] and a["breaker_pct"] == 15
    assert any("not accepted" in line for line in out)
    assert a["acknowledgement"] == ACK


def test_cli_questions_and_build_from_answers(root: Path, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Expected: questions exports JSON; build --answers writes files; bad JSON exits 2."""
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(root))
    r = CliRunner().invoke(app, ["profile", "questions"])
    assert r.exit_code == 0 and json.loads(r.stdout)["bank_version"] == 1
    ans = tmp_path / "answers.json"
    ans.write_text(json.dumps({"answers": _answers(profile_id="from-web")}))
    docs = tmp_path / "docs"
    r = CliRunner().invoke(
        app, ["profile", "build", "--answers", str(ans), "--docs-dir", str(docs)]
    )
    assert r.exit_code == 0, r.output
    assert (root / "profiles" / "from-web.yaml").exists()
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    r = CliRunner().invoke(app, ["profile", "build", "--answers", str(bad)])
    assert r.exit_code == 2


def test_session_defaults_follow_trading_spec(root: Path, tmp_path: Path) -> None:
    """Expected: a built profile's spec sets the session; explicit options win; none = 4h."""
    from trader.profiles.compiler import compile_bundle as cb
    from trader.session.config import session_defaults

    a = _answers(profile_id="quick-mr", decision_timeframe="1h", strategy_id="mean_reversion")
    res = build(a, root, tmp_path / "docs", now=NOW)
    prof = cb(res.profile_path, Environment.BACKTEST, None, root).profile
    assert session_defaults(prof, None, None) == ("mean_reversion", "1h")
    assert session_defaults(prof, "tsmom", "4h") == ("tsmom", "4h")
    assert session_defaults(None, None, None) == ("sma_trend", "4h")


def test_web_form_is_built_from_current_bank() -> None:
    """Expected: the published form embeds exactly the current bank (rerun the script if not)."""
    import importlib.util

    from tests.conftest import ROOT

    spec = importlib.util.spec_from_file_location("bpf", ROOT / "scripts" / "build_profile_form.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    page = (ROOT / "docs" / "profile-builder" / "index.html").read_text()
    assert page == mod.render(), "run: uv run python scripts/build_profile_form.py"
    assert mod.MARK not in page
