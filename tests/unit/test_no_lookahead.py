"""T-20: future-perturbation test (LA-01) and feature causality (LA-02)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.helpers import series
from trader.data.frames import candles_to_frame
from trader.data.snapshots import SnapshotBuilder
from trader.domain.candles import Candle
from trader.domain.market import DatasetManifest, SourceRef
from trader.features.definitions import FEATURE_WINDOW_BARS
from trader.features.pipeline import compute_features
from trader.regimes.null_classifier import assess
from trader.strategies.base import SignalIds
from trader.strategies.sma_trend import SmaTrend

N = 90


def _manifest(c: list[Candle]) -> DatasetManifest:
    return DatasetManifest(
        schema_version="1.0.0",
        dataset_id="ds-test",
        instrument_id="BTC-USD",
        timeframe="4h",
        source=SourceRef(provider_id="t", venue_id="sim", retrieved_at_utc=None),
        source_label="t",
        row_count=len(c),
        first_open_time_utc=c[0].open_time_utc,
        last_open_time_utc=c[-1].open_time_utc,
        content_hash="x",
        parquet_sha256="x",
        quality_status="ok",
        quality_issues=[],
        gaps=[],
    )


def _outputs(candles: list[Candle], upto: int) -> list[tuple[object, ...]]:
    b = SnapshotBuilder("4h")
    b.add(_manifest(candles), candles_to_frame(candles))
    out = []
    for i in range(upto + 1):
        t = candles[i].close_time_utc
        snap = b.snapshot("BTC-USD", t, "c", "s")
        fs = compute_features(
            b.window("BTC-USD", t, FEATURE_WINDOW_BARS), "BTC-USD", "4h", t, "f", ["ds"]
        )
        assert fs.max_input_close_time_utc <= fs.as_of_utc
        sig = SmaTrend().generate(snap, fs, assess(snap, fs, "r"), SignalIds("s", "c", "c"))
        out.append((snap, fs, [s.side for s in sig]))
    return out


@settings(max_examples=25, deadline=None)
@given(
    base=st.lists(st.integers(50, 150), min_size=N, max_size=N),
    cut=st.integers(55, N - 2),
    noise=st.lists(st.integers(5, 400), min_size=N, max_size=N),
)
def test_t20_future_perturbation(base: list[int], cut: int, noise: list[int]) -> None:
    """T-20: perturbing candles after t leaves everything at or before t unchanged."""
    original = series(base)
    perturbed_closes = base[: cut + 1] + noise[cut + 1 :]
    perturbed = series(perturbed_closes)
    assert original[: cut + 1] == perturbed[: cut + 1]
    assert _outputs(original, cut) == _outputs(perturbed, cut)


def test_snapshot_never_contains_future_bar() -> None:
    """LA-02: a window at t excludes the bar closing after t."""
    c = series([Decimal(100 + i) for i in range(60)])
    b = SnapshotBuilder("4h")
    b.add(_manifest(c), candles_to_frame(c))
    t = c[30].close_time_utc + timedelta(hours=2)
    assert b.window("BTC-USD", t, 500)[-1] == c[30]
    assert not b.snapshot("BTC-USD", t, "c", "s").is_fresh
