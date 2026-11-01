"""T-11 to T-16: data-quality checks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from tests.helpers import T0, frame, hours, series
from trader.data.providers.csv_provider import CsvCandleProvider
from trader.data.quality import run_quality_checks
from trader.data.snapshots import SnapshotBuilder
from trader.data.store import DataQualityError, DatasetStore
from trader.domain.candles import Candle
from trader.domain.market import SourceRef

SRC = SourceRef(provider_id="test", venue_id="csv", retrieved_at_utc=None)


def _codes(rep, sev: str) -> set[str]:  # type: ignore[no-untyped-def]
    return {i.check_id for i in rep.issues if i.severity == sev}


def test_clean_frame_ok() -> None:
    """Expected: a clean frame has no errors."""
    rows = [(T0 + hours(i), 10, 11, 9, 10, 1) for i in range(5)]
    rep = run_quality_checks(frame(rows), "1h", None)
    assert rep.ok and not rep.gaps


def test_t11_conflicting_duplicates_rejected() -> None:
    """T-11: same open time, different close -> DQ-05 error; dataset not created."""
    rows = [(T0, 10, 11, 9, 10, 1), (T0, 10, 11, 9, 10.5, 1), (T0 + hours(1), 10, 11, 9, 10, 1)]
    rep = run_quality_checks(frame(rows), "1h", None)
    assert "DQ-05" in _codes(rep, "error")
    store = DatasetStore()
    with pytest.raises(DataQualityError):
        store.create_from_frame(frame(rows), "BTC-USD", "1h", SRC, "t11")
    assert store.list() == []


def test_exact_duplicates_dropped() -> None:
    """Edge: exact duplicates are dropped with a warning."""
    rows = [(T0, 10, 11, 9, 10, 1), (T0, 10, 11, 9, 10, 1), (T0 + hours(1), 10, 11, 9, 10, 1)]
    rep = run_quality_checks(frame(rows), "1h", None)
    assert rep.ok and "DQ-05" in _codes(rep, "warning") and len(rep.frame) == 2


def test_t12_misordered_sorted_and_misaligned_rejected() -> None:
    """T-12: out-of-order rows sorted with a warning; 01:30 for 1h is a DQ-03 error."""
    rows = [(T0 + hours(1), 10, 11, 9, 10, 1), (T0, 10, 11, 9, 10, 1)]
    rep = run_quality_checks(frame(rows), "1h", None)
    assert rep.ok and "DQ-04" in _codes(rep, "warning")
    assert list(rep.frame["open_time_utc"]) == [T0, T0 + hours(1)]
    bad = rows + [(T0.replace(hour=1, minute=30), 10, 11, 9, 10, 1)]
    assert "DQ-03" in _codes(run_quality_checks(frame(bad), "1h", None), "error")


@pytest.mark.parametrize(
    "row",
    [(T0, 10, 11, 9, 12, 1), (T0, 8, 11, 9, 10, 1), (T0, 0, 11, 0, 10, 1)],
    ids=["high_below_close", "low_above_open", "zero_price"],
)
def test_t13_ohlc_inconsistent(row: tuple[object, ...]) -> None:
    """T-13: high < close, low > open, price 0 -> DQ-07 error."""
    assert "DQ-07" in _codes(run_quality_checks(frame([row]), "1h", None), "error")


def test_t13_negative_volume() -> None:
    """Failure: negative volume -> DQ-08 error."""
    assert "DQ-08" in _codes(
        run_quality_checks(frame([(T0, 10, 11, 9, 10, -1)]), "1h", None), "error"
    )


def test_t14_naive_timestamps(tmp_path: Path) -> None:
    """T-14: naive datetime in CSV and in a Candle -> NAIVE_TIMESTAMP."""
    p = tmp_path / "c.csv"
    p.write_text("open_time_utc,open,high,low,close,volume\n2024-01-01T00:00:00,10,11,9,10,1\n")
    rep = run_quality_checks(CsvCandleProvider(p).read_frame(), "1h", None)
    assert any(i.check_id == "DQ-02" and i.message == "NAIVE_TIMESTAMP" for i in rep.errors)
    with pytest.raises(ValueError, match="NAIVE_TIMESTAMP"):
        Candle(
            open_time_utc=datetime(2024, 1, 1),
            close_time_utc=datetime(2024, 1, 1, 1),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )


def test_csv_epoch_ms_and_z(tmp_path: Path) -> None:
    """Expected: ISO with Z and epoch milliseconds both parse as UTC."""
    p = tmp_path / "c.csv"
    p.write_text(
        "open_time_utc,open,high,low,close,volume\n"
        "2024-01-01T00:00:00Z,10,11,9,10,1\n1704070800000,10,11,9,10,1\n"
    )
    rep = run_quality_checks(CsvCandleProvider(p).read_frame(), "1h", None)
    assert rep.ok and len(rep.frame) == 2


def test_t15_gaps_warned_not_filled() -> None:
    """T-15: gaps listed as warnings, never filled; snapshot at a missing close is stale."""
    candles = series([10, 11, 12, 13, 14])
    del candles[2]
    store = DatasetStore()
    m = store.create(candles, "BTC-USD", "4h", SRC, "gap")
    assert m.gaps and m.row_count == 4
    assert any(i.check_id == "DQ-06" and i.severity == "warning" for i in m.quality_issues)
    b = SnapshotBuilder("4h")
    b.add(*store.load(m.dataset_id))
    missing_close = candles[1].close_time_utc + hours(4)
    assert not b.snapshot("BTC-USD", missing_close, "c", "s").is_fresh
    assert b.snapshot("BTC-USD", candles[1].close_time_utc, "c", "s").is_fresh


def test_t16_incomplete_last_candle_dropped() -> None:
    """T-16: last candle closing after retrieved_at is dropped with DQ-11."""
    rows = [(T0 + hours(i), 10, 11, 9, 10, 1) for i in range(3)]
    rep = run_quality_checks(frame(rows), "1h", T0 + hours(2) + hours(1) - hours(1) / 2)
    assert "DQ-11" in _codes(rep, "warning") and len(rep.frame) == 2
