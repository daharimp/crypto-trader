"""ADR-051: ``scripts/ops/start_new.sh`` starts a paper service that a deploy added.

Runs the real script with ``docker``, ``git`` and ``curl`` replaced by stubs, so no network
or containers are needed. A folder in the temp dir holds one file per existing container.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "start_new.sh"
OLD = ("paper", "perps", "perps-degen", "perps-spot-perps", "review", "dashboard")
SHA = "0123456789abcdef0123456789abcdef01234567"

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock (Linux)")


class Server:
    """A fake server: which services have a container, and whether ``up`` works."""

    def __init__(self, tmp: Path) -> None:
        self.bot = tmp / "bot"
        self.state = tmp / "state"
        self.containers = tmp / "containers"
        self.alerts_file = tmp / "alerts.txt"
        self.docker_file = tmp / "docker.txt"
        self.up_fails = tmp / "up-fails"
        self.head = tmp / "head-sha"
        self.bot.mkdir()
        self.state.mkdir()
        self.containers.mkdir()
        (self.bot / ".env").write_text("ALERT_WEBHOOK_URL=https://example.invalid/topic\n")
        self.head.write_text(SHA + "\n")
        (self.state / "deployed-sha").write_text(SHA + "\n")
        for svc in OLD:
            (self.containers / svc).touch()
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "curl").write_text(
            '#!/bin/sh\ncase "$*" in *" -d "*) echo "$@" >>"' + str(self.alerts_file) + '";; esac\n'
        )
        (bin_dir / "git").write_text('#!/bin/sh\ncat "' + str(self.head) + '"\n')
        # docker compose ps --all -q <svc>: an id if the service has a container, running or
        # not. docker compose up -d --no-build <svc>: creates it unless the flag says fail.
        (bin_dir / "docker").write_text(
            "#!/bin/sh\n"
            'echo "$@" >>"' + str(self.docker_file) + '"\n'
            "for last; do :; done\n"
            'case "$*" in\n'
            '  "compose ps --all -q "*) [ -f "' + str(self.containers) + '/$last" ] && echo id;;\n'
            '  "compose up -d --no-build "*)\n'
            '    [ -f "' + str(self.up_fails) + '" ] && exit 1\n'
            '    touch "' + str(self.containers) + '/$last";;\n'
            "esac\n"
            "exit 0\n"
        )
        for f in bin_dir.iterdir():
            f.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(tmp),
            "CRYPTO_TRADER_DIR": str(self.bot),
            "OPS_STATE_DIR": str(self.state),
            "NEW_SERVICE_WAIT": "0",
        }

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT)], env=self.env, capture_output=True, text=True, timeout=60
        )

    def alerts(self) -> list[str]:
        return self.alerts_file.read_text().splitlines() if self.alerts_file.exists() else []

    def ups(self) -> list[str]:
        calls = self.docker_file.read_text().splitlines() if self.docker_file.exists() else []
        return [c for c in calls if " up " in c]


@pytest.fixture
def server(tmp_path: Path) -> Server:
    return Server(tmp_path)


def test_a_service_added_by_the_last_deploy_is_started_once(server: Server) -> None:
    r = server.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert server.ups() == ["compose up -d --no-build perps-top10"]  # never a build
    assert len(server.alerts()) == 1 and "started the new service perps-top10" in server.alerts()[0]
    assert server.run().returncode == 0
    assert len(server.ups()) == 1 and len(server.alerts()) == 1  # it exists now: left alone


def test_existing_containers_and_a_stack_taken_down_are_left_alone(server: Server) -> None:
    (server.containers / "perps-top10").touch()  # exists (perhaps stopped by the owner)
    assert server.run().returncode == 0
    assert server.ups() == [] and server.alerts() == []
    for f in server.containers.iterdir():  # `docker compose down`: the owner's choice
        f.unlink()
    assert server.run().returncode == 0
    assert server.ups() == [] and server.alerts() == []


def test_nothing_starts_unless_the_last_deploy_built_this_commit(server: Server) -> None:
    server.head.write_text("f" * 40 + "\n")  # pulled by hand, or a deploy on hold: old image
    assert server.run().returncode == 0
    assert server.ups() == []
    (server.state / "deployed-sha").unlink()  # never deployed by automation
    server.head.write_text("\n")
    assert server.run().returncode == 0
    assert server.ups() == [] and server.alerts() == []


def test_a_failed_start_alerts_once_and_never_names_live(server: Server) -> None:
    server.up_fails.touch()
    assert [server.run().returncode for _ in range(3)] == [0, 0, 0]
    assert len(server.ups()) == 3  # it keeps trying every run
    assert len(server.alerts()) == 1 and "could not start the new service" in server.alerts()[0]
    server.up_fails.unlink()
    assert server.run().returncode == 0
    assert "started the new service perps-top10" in server.alerts()[-1]
    assert not any("live" in c for c in server.docker_file.read_text().splitlines())


def test_every_listed_paper_service_exists_in_compose_and_live_is_not_listed() -> None:
    line = next(
        row
        for row in (ROOT / "scripts/ops/common.sh").read_text().splitlines()
        if row.startswith("PAPER_SERVICES=")
    )
    listed = line.split("(", 1)[1].rstrip(")").split()
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    assert listed == [*OLD[:4], "perps-top10", *OLD[4:]]
    assert all(s in services and "profiles" not in services[s] for s in listed)
    assert "live" not in listed
