"""T-17 and T-18: dataset identity and immutability."""

from __future__ import annotations

import os
import stat
from decimal import Decimal

import pytest

from tests.helpers import T0, series
from trader.common.clock import parse_utc
from trader.data.providers.synthetic import SyntheticCandleProvider
from trader.data.store import DatasetIntegrityError, DatasetNotFoundError, DatasetStore
from trader.domain.market import SourceRef

SRC = SourceRef(provider_id="synthetic", venue_id="sim", retrieved_at_utc=None)


def test_t17_same_input_same_id() -> None:
    """T-17: same candles twice -> same dataset_id, one directory."""
    store = DatasetStore()
    c = series([10, 11, 12])
    a = store.create(c, "BTC-USD", "4h", SRC, "x")
    b = store.create(c, "BTC-USD", "4h", SRC, "x")
    assert a == b and a.dataset_id.startswith("ds-") and len(a.dataset_id) == 19
    assert len(list(store.root.iterdir())) == 1


def test_label_changes_id() -> None:
    """Edge: the source label is part of the identity."""
    store = DatasetStore()
    c = series([10, 11, 12])
    assert (
        store.create(c, "BTC-USD", "4h", SRC, "x").dataset_id
        != store.create(c, "BTC-USD", "4h", SRC, "y").dataset_id
    )


def test_synthetic_is_deterministic() -> None:
    """Expected: the same seed gives the same candles; a different seed differs."""
    s, e = parse_utc("2024-01-01T00:00:00Z"), parse_utc("2024-02-01T00:00:00Z")
    a = SyntheticCandleProvider(1, Decimal(100)).fetch_candles("BTC-USD", "4h", s, e)
    b = SyntheticCandleProvider(1, Decimal(100)).fetch_candles("BTC-USD", "4h", s, e)
    c = SyntheticCandleProvider(2, Decimal(100)).fetch_candles("BTC-USD", "4h", s, e)
    assert a == b and a != c and len(a) == 31 * 6 and a[0].open == Decimal(100)


def test_synthetic_rejects_misaligned_start() -> None:
    """Failure: misaligned start."""
    with pytest.raises(ValueError):
        SyntheticCandleProvider(1, Decimal(100)).fetch_candles(
            "BTC-USD", "4h", T0.replace(hour=1), T0.replace(day=2)
        )


def test_t18_tampered_dataset_detected() -> None:
    """T-18: modifying the stored Parquet -> DATASET_INTEGRITY_FAILED."""
    store = DatasetStore()
    m = store.create(series([10, 11, 12]), "BTC-USD", "4h", SRC, "x")
    pq = store.root / m.dataset_id / "candles.parquet"
    assert not os.access(pq, os.W_OK) or os.geteuid() == 0  # read-only (root bypasses)
    os.chmod(pq, stat.S_IRUSR | stat.S_IWUSR)
    pq.write_bytes(pq.read_bytes() + b"x")
    with pytest.raises(DatasetIntegrityError, match="DATASET_INTEGRITY_FAILED"):
        store.load(m.dataset_id)


def test_unknown_dataset() -> None:
    """Failure: unknown ID."""
    with pytest.raises(DatasetNotFoundError):
        DatasetStore().load("ds-0000000000000000")
