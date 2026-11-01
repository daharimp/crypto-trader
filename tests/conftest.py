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


def make_datasets(days: int = 120, start: str = "2024-01-01T00:00:00Z") -> list[str]:
    """Create BTC (seed 42) and ETH (seed 43) synthetic 4h datasets; return their IDs."""
    from datetime import timedelta
    from decimal import Decimal

    from trader.common.clock import parse_utc
    from trader.data.providers.synthetic import SyntheticCandleProvider
    from trader.data.store import DatasetStore
    from trader.domain.market import SourceRef

    s = parse_utc(start)
    ids = []
    for inst, seed, px in (("BTC-USD", 42, "30000"), ("ETH-USD", 43, "2000")):
        prov = SyntheticCandleProvider(seed, Decimal(px))
        candles = prov.fetch_candles(inst, "4h", s, s + timedelta(days=days))
        src = SourceRef(provider_id="synthetic", venue_id="sim", retrieved_at_utc=None)
        ids.append(
            DatasetStore().create(candles, inst, "4h", src, f"synthetic:seed={seed}").dataset_id
        )
    return ids


def small_run(**kw: Any):  # type: ignore[no-untyped-def]
    """Run a short fixture backtest (120 days, decisions from day 31)."""
    from trader.backtest.runner import run_backtest
    from trader.common.clock import parse_utc

    ids = kw.pop("datasets", None) or make_datasets()
    args = dict(
        profile=PROFILE,
        datasets=ids,
        strategy="sma_trend",
        timeframe="4h",
        experiment=EXP_FIXTURE,
        cost_scenario=None,
        start_utc=parse_utc("2024-02-01T00:00:00Z"),
        end_utc=None,
    )
    args.update(kw)
    return run_backtest(**args)
