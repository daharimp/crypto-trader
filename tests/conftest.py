"""Shared pytest fixtures. Every test gets an isolated ``TRADER_DATA_DIR``."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "configs" / "profiles" / "balanced-paper.yaml"
EXP_2026_001 = ROOT / "experiments" / "EXP-2026-001-vertical-slice.yaml"
EXP_FIXTURE = ROOT / "tests" / "fixtures" / "experiments" / "EXP-0000-001-e2e.yaml"


@pytest.fixture(autouse=True)
def _isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the data directory at a per-test temp folder and run from the repo root."""
    data = tmp_path / "data"
    monkeypatch.setenv("TRADER_DATA_DIR", str(data))
    monkeypatch.setenv("TRADER_CODE_REVISION", "test-revision")
    monkeypatch.chdir(ROOT)
    return data


def load(path: Path) -> Any:
    """Load YAML from a path."""
    return yaml.safe_load(path.read_text())


def dump(path: Path, data: Any) -> Path:
    """Write YAML to a path (creating parents) and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


@pytest.fixture
def profile_data() -> dict[str, Any]:
    """A deep copy of the shipped Balanced profile."""
    return copy.deepcopy(load(PROFILE))


@pytest.fixture
def configs_copy(tmp_path: Path) -> Path:
    """A writable copy of ``configs/`` for tests that need modified risk files."""
    dst = tmp_path / "configs"
    shutil.copytree(ROOT / "configs", dst)
    return dst


@pytest.fixture
def fixture_experiment(tmp_path: Path):
    """Factory: write a fixture experiment (EXP-0000-*) with overridden risk parameters."""

    def make(
        risk: dict[str, Any] | None = None,
        eligibility: dict[str, Any] | None = None,
        exp_id: str = "EXP-0000-099",
    ) -> Path:
        data = copy.deepcopy(load(EXP_FIXTURE))
        data["experiment_id"] = exp_id
        for k, v in (risk or {}).items():
            data["parameters"]["risk"][k] = {"value": v, "source": "test fixture"}
        for k, v in (eligibility or {}).items():
            data["parameters"]["eligibility"][k] = {"value": v, "source": "test fixture"}
        return dump(tmp_path / "fixtures" / f"{exp_id}.yaml", data)

    return make
