"""ADR-050: ``scripts/ops/dashboard_check.sh`` restarts a dashboard that stops answering.

Runs the real script with ``docker``, ``tailscale`` and ``curl`` replaced by stubs, so no
network or containers are needed. A file in the temp dir decides whether the page answers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "dashboard_check.sh"

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock (Linux)")


class Server:
    """A fake server whose dashboard is up or down, and whose docker restart can fix it."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.bot = tmp / "bot"
        self.state = tmp / "state"
        self.alerts_file = tmp / "alerts.txt"
        self.docker_file = tmp / "docker.txt"
        self.up_flag = tmp / "dashboard-up"
        self.fix_flag = tmp / "restart-fixes"
        self.serve_flag = tmp / "tailscale-serving"
        (self.bot / "data").mkdir(parents=True)
        (self.bot / ".env").write_text("ALERT_WEBHOOK_URL=https://example.invalid/topic\n")
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        # curl: a notify call posts with -d; a probe succeeds only while the page is up.
        (bin_dir / "curl").write_text(
            "#!/bin/sh\n"
            'case "$*" in *" -d "*) echo "$@" >>"' + str(self.alerts_file) + '"; exit 0;; esac\n'
            '[ -f "' + str(self.up_flag) + '" ]\n'
        )
        (bin_dir / "docker").write_text(
            "#!/bin/sh\n"
            'echo "$@" >>"' + str(self.docker_file) + '"\n'
            'case "$*" in *"ps --status running"*) echo dashboard;; esac\n'
            'case "$*" in *restart*|*"up -d"*) [ -f "' + str(self.fix_flag) + '" ] && '
            'touch "' + str(self.up_flag) + '";; esac\n'
            "exit 0\n"
        )
        (bin_dir / "tailscale").write_text(
            "#!/bin/sh\n"
            '[ -f "' + str(self.serve_flag) + '" ] && echo "|-- / proxy http://127.0.0.1:8787"\n'
            "exit 0\n"
        )
        for f in bin_dir.iterdir():
            f.chmod(0o755)
        self.serve_flag.touch()
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(tmp),
            "CRYPTO_TRADER_DIR": str(self.bot),
            "OPS_STATE_DIR": str(self.state),
            "DASHBOARD_PROBE_TRIES": "2",
            "DASHBOARD_PROBE_DELAY": "0",
            "DASHBOARD_RESTART_WAIT": "0",
        }

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT)], env=self.env, capture_output=True, text=True, timeout=60
        )

    def alerts(self) -> list[str]:
        return self.alerts_file.read_text().splitlines() if self.alerts_file.exists() else []

    def docker_calls(self) -> list[str]:
        return self.docker_file.read_text().splitlines() if self.docker_file.exists() else []


@pytest.fixture
def server(tmp_path: Path) -> Server:
    return Server(tmp_path)


def test_healthy_dashboard_is_left_alone(server: Server) -> None:
    server.up_flag.touch()
    r = server.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any("restart" in c for c in server.docker_calls())
    assert server.alerts() == []
    assert "ok" in (server.bot / "data" / "ops" / "dashboard.txt").read_text()


def test_hung_dashboard_is_restarted_and_alerts_once(server: Server) -> None:
    server.fix_flag.touch()  # a restart brings it back
    r = server.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "compose restart dashboard" in server.docker_calls()
    # Only the dashboard is touched, never a bot service, and never a build.
    assert all("paper" not in c and "perps" not in c for c in server.docker_calls())
    assert len(server.alerts()) == 1 and "back up" in server.alerts()[0]


def test_stays_down_alerts_then_gives_up_restarting(server: Server) -> None:
    results = [server.run() for _ in range(4)]
    assert all(r.returncode == 1 for r in results)
    restarts = [c for c in server.docker_calls() if "restart" in c]
    assert len(restarts) == 3  # capped at 3 an hour, no restart loop
    alerts = server.alerts()
    assert len(alerts) == 1 and "DOWN" in alerts[0]  # one alert, not one per run

    server.up_flag.touch()
    assert server.run().returncode == 0
    assert "back up" in server.alerts()[-1]


def test_alerts_when_tailscale_stops_serving(server: Server) -> None:
    server.up_flag.touch()
    server.serve_flag.unlink()
    assert server.run().returncode == 0
    assert server.run().returncode == 0
    alerts = server.alerts()
    assert len(alerts) == 1 and "tailscale serve --bg 8787" in alerts[0]
    server.serve_flag.touch()
    server.run()
    assert "serving the dashboard again" in server.alerts()[-1]
