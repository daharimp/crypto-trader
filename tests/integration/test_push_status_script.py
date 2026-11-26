"""ADR-047: ``scripts/ops/push_status.sh`` survives an ops repo that moved on without it.

Runs the real script against local git repos, with ``docker``, ``tailscale`` and ``curl``
replaced by stubs, so no network or containers are needed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "push_status.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("flock") is None,
    reason="needs git and flock (Linux)",
)


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


class Server:
    """A fake server: bot repo, ops clone, bare ops remote, and stubbed tools."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.remote = tmp / "ops.git"
        self.clone = tmp / "ops-clone"
        self.state = tmp / "state"
        self.bot = tmp / "bot"
        self.calls = tmp / "curl-calls.txt"
        _git(tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        # Upstream starts with one server snapshot, like the real ops repo did.
        seed = tmp / "seed"
        _git(tmp, "clone", "-q", str(self.remote), str(seed))
        (seed / "health.json").write_text('{"v": 0}\n')
        _git(seed, "add", "-A")
        _git(seed, "commit", "-qm", "status 0")
        _git(seed, "push", "-q", "origin", "HEAD:main")
        _git(tmp, "clone", "-q", str(self.remote), str(self.clone))

        (self.bot / "data" / "ops").mkdir(parents=True)
        (self.bot / ".env").write_text("ALERT_WEBHOOK_URL=https://example.invalid/topic\n")
        _git(self.bot, "init", "-q")
        _git(self.bot, "commit", "-q", "--allow-empty", "-m", "deployed")

        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        for name in ("docker", "tailscale"):
            (bin_dir / name).write_text("#!/bin/sh\nexit 0\n")
        (bin_dir / "curl").write_text(f'#!/bin/sh\necho "$@" >>"{self.calls}"\n')
        for f in bin_dir.iterdir():
            f.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(tmp),
            "CRYPTO_TRADER_DIR": str(self.bot),
            "OPS_STATE_DIR": str(self.state),
            "OPS_REPO_DIR": str(self.clone),
            "OPS_REMOTE": str(self.remote),
            "PUSH_RETRY_DELAY": "0",
            "GIT_CONFIG_GLOBAL": str(tmp / "gitconfig"),
        }

    def snapshot(self, value: int) -> None:
        (self.bot / "data" / "ops" / "health.json").write_text(f'{{"v": {value}}}\n')

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT)], env=self.env, capture_output=True, text=True, timeout=60
        )

    def upstream_commit(self, path: str, text: str) -> None:
        """Commit to the ops repo from elsewhere, like the daily review does."""
        other = self.tmp / "reviewer"
        if not other.exists():
            _git(self.tmp, "clone", "-q", str(self.remote), str(other))
        _git(other, "pull", "-q", "--rebase", "origin", "main")
        target = other / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        _git(other, "add", "-A")
        _git(other, "commit", "-qm", f"review {path}")
        _git(other, "push", "-q", "origin", "HEAD:main")

    def remote_file(self, path: str) -> str:
        return _git(self.tmp, "--git-dir", str(self.remote), "show", f"main:{path}")

    def alerts(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []


@pytest.fixture
def server(tmp_path: Path) -> Server:
    return Server(tmp_path)


def test_recovers_backlog_after_upstream_review_commit(server: Server) -> None:
    # Reproduces Nov 24-26: unpushed local snapshots, then reviews/ committed upstream.
    for v in (1, 2):
        (server.clone / "health.json").write_text(f'{{"v": {v}}}\n')
        _git(server.clone, "add", "-A")
        _git(server.clone, "commit", "-qm", f"status {v}")
    server.upstream_commit("reviews/daily-2026-11-24.md", "review\n")
    server.snapshot(3)

    r = server.run()

    assert r.returncode == 0, r.stdout + r.stderr
    assert server.remote_file("health.json") == '{"v": 3}'
    assert server.remote_file("reviews/daily-2026-11-24.md") == "review"
    assert server.alerts() == []


def test_conflict_keeps_reviews_and_server_snapshot(server: Server) -> None:
    server.upstream_commit("reviews/daily.md", "keep me\n")
    server.upstream_commit("health.json", '{"v": "edited upstream"}\n')
    (server.clone / "health.json").write_text('{"v": "local"}\n')
    _git(server.clone, "commit", "-qam", "status local")
    server.snapshot(9)

    r = server.run()

    assert r.returncode == 0, r.stdout + r.stderr
    assert server.remote_file("health.json") == '{"v": 9}'
    assert server.remote_file("reviews/daily.md") == "keep me"


def test_failed_push_alerts_once_then_reports_recovery(server: Server) -> None:
    hook = server.remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    server.snapshot(1)

    first = server.run()
    server.snapshot(2)
    second = server.run()

    assert first.returncode == 1 and second.returncode == 1
    alerts = server.alerts()
    assert len(alerts) == 1 and "FAILED" in alerts[0]

    hook.unlink()
    server.snapshot(3)
    third = server.run()

    assert third.returncode == 0, third.stdout + third.stderr
    assert server.remote_file("health.json") == '{"v": 3}'
    assert len(server.alerts()) == 2 and "recovered" in server.alerts()[1]


def test_nothing_new_still_succeeds(server: Server) -> None:
    server.snapshot(0)
    assert server.run().returncode == 0
    assert server.run().returncode == 0
    assert server.alerts() == []
