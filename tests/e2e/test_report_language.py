"""T-48: report has the disclaimer, provenance banner, and no profitability claims."""

from __future__ import annotations

import json
import re
from typing import Any

from trader.evaluation.report import DISCLAIMER

FORBIDDEN = re.compile(r"guarantee|risk-free|will earn", re.IGNORECASE)


def test_t48_report_language(slice_run: dict[str, Any]) -> None:
    """T-48: disclaimer present; banner lists experiment and hypothesis values; no claims."""
    md = (slice_run["report_dir"] / "report.md").read_text()
    js = json.loads((slice_run["report_dir"] / "report.json").read_text())
    assert md.startswith(f"> **{DISCLAIMER}**") and js["disclaimer"] == DISCLAIMER
    provs = {v["provenance"] for v in js["provenance"]["non_approved_values"]}
    assert {"hypothesis", "fixture"} <= provs
    assert "H-01" in md and "UD-01" in md
    # The disclaimer's own "not guaranteed" is the only permitted mention.
    assert not FORBIDDEN.search(md.replace(DISCLAIMER, ""))
    assert not FORBIDDEN.search(json.dumps({k: v for k, v in js.items() if k != "disclaimer"}))
