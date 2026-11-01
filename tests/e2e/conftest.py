"""E2E helpers: drive the real CLI in-process."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from trader.cli.main import app

PROFILE = "configs/profiles/balanced-paper.yaml"
FIXTURE = "tests/fixtures/experiments/EXP-0000-001-e2e.yaml"


def cli(*args: str, expect: int = 0) -> Any:
    """Invoke ``trader`` and assert the exit code."""
    res = CliRunner().invoke(app, list(args))
    assert res.exit_code == expect, (args, res.exit_code, res.output[-3000:])
    return res


def vertical_slice() -> dict[str, Any]:
    """T-42 flow: synth BTC/ETH (4h, 400 days), validate, backtest, report, verify."""
    ids = []
    for inst, seed, px in (("BTC-USD", "42", "30000"), ("ETH-USD", "43", "2000")):
        out = cli(
            "data",
            "synth",
            "--instrument",
            inst,
            "--timeframe",
            "4h",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2025-02-04T00:00:00Z",
            "--seed",
            seed,
            "--start-price",
            px,
        ).stdout
        ids.append(out.strip().splitlines()[-1])
    for d in ids:
        cli("data", "validate", d)
    run = cli(
        "backtest",
        "run",
        "--profile",
        PROFILE,
        "--experiment",
        FIXTURE,
        "--datasets",
        ",".join(ids),
        "--strategy",
        "sma_trend",
        "--timeframe",
        "4h",
        "--start",
        "2024-02-15T00:00:00Z",
    ).stdout
    run_id = re.search(r"run_id: (\S+)", run).group(1)  # type: ignore[union-attr]
    data = Path(os.environ["TRADER_DATA_DIR"])
    return {"ids": ids, "run_id": run_id, "data": data, "report_dir": data / "reports" / run_id}


@pytest.fixture
def slice_run() -> dict[str, Any]:
    """One vertical-slice run."""
    return vertical_slice()
