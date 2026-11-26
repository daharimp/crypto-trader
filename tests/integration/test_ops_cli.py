"""ADR-047: ``trader ops health`` writes a snapshot and de-duplicates alerts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trader.cli.main import app

ROOT = Path(__file__).resolve().parents[2]
SERVICES = (
    "paper",
    "perps",
    "perps-degen",
    "perps-spot-perps",
    "perps-top10",
    "review",
    "dashboard",
)


def test_health_writes_snapshot_and_alerts_once(
    _isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(ROOT / "configs"))
    sent: list[str] = []
    monkeypatch.setattr(
        "trader.session.alerts.Alerter.send", lambda self, text: sent.append(text) or True
    )
    ops = _isolated_data / "ops"
    ops.mkdir(parents=True)
    rows = [{"Service": s, "State": "running"} for s in SERVICES if s != "review"]
    (ops / "ps.json").write_text(json.dumps(rows))
    (ops / "logs.txt").write_text("crypto-trader-perps-1  | INFO fine\n")
    args = ["ops", "health", "--containers", str(ops / "ps.json"), "--logs", str(ops / "logs.txt")]

    r = CliRunner().invoke(app, [*args, "--commit", "abc123", "--alert"])
    assert r.exit_code == 0, r.output
    snap = json.loads((ops / "health.json").read_text())
    assert snap["commit"] == "abc123" and snap["ok"] is False
    keys = {p["key"] for p in snap["problems"]}
    assert "container:review" in keys
    # Real configs resolve a stop for every perps account, so none is flagged.
    assert not any(k.endswith(":config") or k.endswith(":stop") for k in keys)
    assert len(sent) == 1 and "review is not created" in sent[0]

    # A second run with the same problems sends nothing new.
    assert CliRunner().invoke(app, [*args, "--alert"]).exit_code == 0
    assert len(sent) == 1


def test_health_unreadable_container_list(_isolated_data: Path) -> None:
    r = CliRunner().invoke(app, ["ops", "health", "--containers", "/nonexistent/ps.json"])
    assert r.exit_code == 0
    assert "container list unreadable" in r.output
