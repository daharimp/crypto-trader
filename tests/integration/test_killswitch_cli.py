"""T-45: persisted kill switch CLI; state survives restarts; history appended."""

from __future__ import annotations

import os
import subprocess
import sys

from typer.testing import CliRunner

from trader.cli.main import app
from trader.risk.controls import KillSwitchError, PersistedKillSwitch


def _new_process(*args: str) -> str:
    out = subprocess.run(
        [sys.executable, "-m", "trader.cli.main", *args],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        check=True,
    )
    return out.stdout


def test_t45_engage_status_restart_disengage() -> None:
    """T-45: engage, status, new-process status, disengage with owner and reason."""
    r = CliRunner()
    assert "disengaged (initial)" in r.invoke(app, ["killswitch", "status"]).stdout
    assert "engaged" in r.invoke(app, ["killswitch", "engage", "--reason", "drill"]).stdout
    assert "state: engaged" in r.invoke(app, ["killswitch", "status"]).stdout
    assert "state: engaged" in _new_process("killswitch", "status")
    res = r.invoke(app, ["killswitch", "disengage", "--reason", "drill complete"])
    assert "changed_by: owner" in res.stdout and "drill complete" in res.stdout
    hist = PersistedKillSwitch().store.killswitch_history()
    assert [h.state for h in hist] == ["engaged", "disengaged"]
    assert hist[-1].changed_by == "owner" and hist[-1].reason == "drill complete"


def test_reason_required() -> None:
    """Failure: blank reasons are refused."""
    assert CliRunner().invoke(app, ["killswitch", "engage", "--reason", " "]).exit_code == 2
    assert CliRunner().invoke(app, ["killswitch", "disengage", "--reason", ""]).exit_code == 2
    import pytest

    with pytest.raises(KillSwitchError):
        PersistedKillSwitch().disengage(
            " ", __import__("datetime").datetime.now(__import__("datetime").UTC)
        )


def test_run_kill_switch_only_owner_disengages() -> None:
    """Automation can only engage the run-scoped switch."""
    from trader.risk.controls import KillSwitch

    ks = KillSwitch()
    assert ks.engage("auto", "reconciliation_mismatch") and not ks.engage("again")
    import pytest

    with pytest.raises(KillSwitchError):
        ks.disengage("auto")
    ks.disengage("owner reviewed", by_owner=True)
    assert not ks.engaged


def test_version_command() -> None:
    """Smoke: ``trader version`` prints the safety statement."""
    out = CliRunner().invoke(app, ["version"]).stdout
    assert "0.1.0" in out and "Paper by default" in out and "No leverage" in out
