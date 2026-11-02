"""Backtests with daily eligibility datasets (as live sessions use) and the universe benchmark."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.conftest import SHIPPED_CONFIGS, SHIPPED_PROFILE, SHIPPED_UNIVERSE, make_datasets
from trader.backtest.runner import run_backtest
from trader.common.clock import parse_utc
from trader.data.providers.synthetic import SyntheticCandleProvider
from trader.data.store import DatasetStore
from trader.domain.market import SourceRef

START = "2025-01-01T00:00:00Z"


def _daily(days: int = 500) -> list[str]:
    """Daily synthetic datasets covering the 4h window and a year before it."""
    end = parse_utc(START) + timedelta(days=130)
    ids = []
    for inst, seed, px in SHIPPED_UNIVERSE:
        c = SyntheticCandleProvider(seed + 100, Decimal(px), Decimal("1e9")).fetch_candles(
            inst, "1d", end - timedelta(days=days), end
        )
        src = SourceRef(provider_id="synthetic", venue_id="sim", retrieved_at_utc=None)
        ids.append(DatasetStore().create(c, inst, "1d", src, f"daily:{seed}").dataset_id)
    return ids


@pytest.fixture
def shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))


def _run(ids: list[str], elig: list[str] | None):  # type: ignore[no-untyped-def]
    return run_backtest(
        SHIPPED_PROFILE,
        ids,
        "sma_trend",
        "4h",
        None,
        None,
        parse_utc(START) + timedelta(days=10),
        None,
        eligibility_datasets=elig,
    )


def test_daily_eligibility_unlocks_short_4h_history(shipped: None) -> None:
    """Expected: 120 days of 4h data + 1d history -> eligible and trading; universe benchmark."""
    r = _run(make_datasets(days=120, start=START, universe=SHIPPED_UNIVERSE), _daily())
    assert r.exit_code == 0, r.message
    rep = json.loads((r.report_path.parent / "report.json").read_text())  # type: ignore[union-attr]
    assert rep["trading"]["order_intents"] > 0
    assert "bm_ew_universe" in rep["benchmarks"]
    assert any(c["benchmark"] == "bm_ew_universe" for c in rep["comparison"])


def test_without_daily_history_nothing_is_eligible(shipped: None) -> None:
    """Edge: 120 days of 4h data alone cannot meet the 365-day rule -> no orders."""
    r = _run(make_datasets(days=120, start=START, universe=SHIPPED_UNIVERSE), None)
    rep = json.loads((r.report_path.parent / "report.json").read_text())  # type: ignore[union-attr]
    assert rep["trading"]["order_intents"] == 0


def test_eligibility_dataset_must_be_daily(shipped: None) -> None:
    """Failure: a 4h dataset passed as eligibility data, or an unknown one, exits 2."""
    ids = make_datasets(days=120, start=START, universe=SHIPPED_UNIVERSE)
    assert _run(ids, ids[:1]).exit_code == 2
    assert _run(ids, ["ds-0000000000000000"]).exit_code == 2
