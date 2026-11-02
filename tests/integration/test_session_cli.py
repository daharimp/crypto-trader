"""CLI: profile activate, session status/flatten/reset-breaker/run gates, live preflight gates."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.session_support import configs
from trader.cli.main import app
from trader.common.opstore import OperationalStore


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = configs(tmp_path)
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(r))
    return r


def _cli(*args: str) -> object:
    return CliRunner().invoke(app, list(args))


def test_activate_paper_then_live_gate(root: Path) -> None:
    """Paper activates; live refuses until the paper track record exists."""
    p = str(root / "profiles" / "balanced-paper.yaml")
    r = _cli("profile", "activate", p, "-e", "paper", "--reason", "start")
    assert r.exit_code == 0 and "activated balanced-paper v4 for paper" in r.stdout
    r = _cli("profile", "activate", p, "-e", "live", "--reason", "go")
    assert r.exit_code == 2 and "paper track record 0 cycles" in r.stdout
    assert _cli("profile", "activate", p, "-e", "backtest", "--reason", "x").exit_code == 2
    assert _cli("profile", "activate", p, "-e", "paper", "--reason", " ").exit_code == 2


def test_session_commands(root: Path) -> None:
    """status with no sessions; owner requests are queued."""
    assert "no sessions yet" in _cli("session", "status").stdout
    r = _cli("session", "flatten", "--reason", "out")
    assert r.exit_code == 0 and OperationalStore().pending_request("flatten")
    assert _cli("session", "reset-breaker", "--reason", "reviewed").exit_code == 0
    assert _cli("session", "flatten", "--reason", "").exit_code == 2


def test_session_run_refuses_without_activation(root: Path) -> None:
    """Failure: `session run` exits 2 before any market call when not activated."""
    p = str(root / "profiles" / "balanced-paper.yaml")
    r = _cli("session", "run", "--profile", p, "-e", "paper", "--once")
    assert r.exit_code == 2 and "activation" in r.output
    r = _cli("session", "run", "--profile", p, "-e", "backtest", "--once")
    assert r.exit_code == 2


def test_live_preflight_needs_keys(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure: preflight without KRAKEN_API_KEY/SECRET exits 2 with instructions."""
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    r = _cli("live", "preflight", "--profile", str(root / "profiles" / "balanced-paper.yaml"))
    assert r.exit_code == 2 and "KRAKEN_API_KEY" in r.output
