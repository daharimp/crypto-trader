"""End-to-end backtest on the owner-approved shipped configs, with no experiment set."""

from __future__ import annotations

import json

import pytest

from tests.conftest import SHIPPED_CONFIGS, SHIPPED_PROFILE, make_datasets
from trader.backtest.runner import run_backtest
from trader.common.clock import parse_utc
from trader.journal.verify import verify


def test_shipped_configs_backtest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expected: runs (exit 0), traceable journal, only hypotheses listed as non-approved."""
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    ids = make_datasets(days=430)
    # Reason: approved UD-18 requires 365 days of history, so decisions start a year in.
    r = run_backtest(
        SHIPPED_PROFILE, ids, "sma_trend", "4h", None, None, parse_utc("2025-01-01T00:00:00Z"), None
    )
    assert r.exit_code == 0, r.message
    rep = json.loads((r.report_path.parent / "report.json").read_text())  # type: ignore[union-attr]
    assert rep["provenance"]["experiment_id"] is None
    assert {v["provenance"] for v in rep["provenance"]["non_approved_values"]} == {"hypothesis"}
    assert rep["trading"]["order_intents"] > 0
    assert verify(r.run_id).ok


def test_shipped_configs_insufficient_history_trades_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge: with under 365 days of history every entry is ASSET_INELIGIBLE."""
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    ids = make_datasets(days=120)
    r = run_backtest(
        SHIPPED_PROFILE, ids, "sma_trend", "4h", None, None, parse_utc("2024-02-01T00:00:00Z"), None
    )
    rep = json.loads((r.report_path.parent / "report.json").read_text())  # type: ignore[union-attr]
    assert r.exit_code == 0 and rep["trading"]["order_intents"] == 0
    assert set(rep["trading"]["rejections_by_reason"]) <= {"ASSET_INELIGIBLE"}
