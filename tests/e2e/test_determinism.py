"""T-43: identical runs give identical journal hashes and report JSON."""

from __future__ import annotations

import json
from typing import Any

from tests.e2e.conftest import vertical_slice


def test_t43_two_runs_identical() -> None:
    """T-43: same root hash; same report.json except run_metadata."""
    a: dict[str, Any] = vertical_slice()
    b: dict[str, Any] = vertical_slice()
    assert a["run_id"] != b["run_id"]
    ra = json.loads((a["report_dir"] / "report.json").read_text())
    rb = json.loads((b["report_dir"] / "report.json").read_text())
    assert ra["journal"]["root_hash"] == rb["journal"]["root_hash"]
    ra.pop("run_metadata")
    rb.pop("run_metadata")
    assert ra == rb
