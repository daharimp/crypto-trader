"""Failure-streak alerts for the server ops scripts (scripts/ops/common.sh, ADR-047)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

COMMON = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "common.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _run(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    """Source common.sh against a throwaway repo dir (no .env, so no webhook) and run body."""
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "CRYPTO_TRADER_DIR": str(repo),
        "OPS_STATE_DIR": str(tmp_path / "state"),
    }
    return subprocess.run(
        ["bash", "-c", f'source "{COMMON}"; {body}'],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_second_failure_in_a_row_alerts(tmp_path: Path) -> None:
    out = _run(tmp_path, 'streak_fail push_status "boom"; streak_fail push_status "boom"')
    assert out.returncode == 0
    lines = [ln for ln in out.stdout.splitlines() if "failing" in ln]
    assert len(lines) == 1
    assert "push_status failing 2 runs in a row: boom" in lines[0]


def test_single_failure_is_quiet_and_success_resets(tmp_path: Path) -> None:
    out = _run(tmp_path, 'streak_fail push_status "blip"; streak_ok push_status')
    assert out.returncode == 0
    assert out.stdout == ""
    assert not (tmp_path / "state" / "push_status.failures").exists()


def test_alert_repeats_daily_then_recovers(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        'for _ in $(seq 26); do streak_fail push_status "down"; done; streak_ok push_status',
    )
    assert out.returncode == 0
    failing = [ln for ln in out.stdout.splitlines() if "failing" in ln]
    # Alerts on runs 2 and 26 only (once a day for an hourly script).
    assert [ln.split("failing ")[1].split(" ")[0] for ln in failing] == ["2", "26"]
    assert "push_status recovered after 26 failed runs" in out.stdout


def test_corrupt_counter_file_starts_over(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "push_status.failures").write_text("garbage\n")
    out = _run(tmp_path, 'streak_fail push_status "x"')
    assert out.returncode == 0
    assert out.stdout == ""
    assert (state / "push_status.failures").read_text().strip() == "1"


def test_lock_skip_counts_as_failure(tmp_path: Path) -> None:
    # Hold the lock from a background process, then try to take it twice.
    out = _run(
        tmp_path,
        'mkdir -p "$OPS_STATE"; (flock "$OPS_STATE/ops.lock" sleep 3) & sleep 0.3; '
        'f() { streak_fail push_status "$1"; }; '
        "(take_lock 0 f); (take_lock 0 f); wait",
    )
    assert out.returncode == 0
    assert out.stdout.count("another ops script is running; skipping") == 2
    assert "push_status failing 2 runs in a row: skipped" in out.stdout
