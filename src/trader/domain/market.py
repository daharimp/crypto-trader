"""Market snapshot and dataset manifest contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from .candles import Candle
from .common import DomainModel, SchemaVersion, UtcDatetime


class SourceRef(DomainModel):
    """Where market data came from."""

    provider_id: str
    venue_id: str
    retrieved_at_utc: UtcDatetime | None


class MarketSnapshot(DomainModel):
    """Point-in-time view of one instrument at a decision time (contract 3)."""

    schema_version: SchemaVersion
    snapshot_id: str
    cycle_id: str
    instrument_id: str
    timeframe: str
    as_of_utc: UtcDatetime
    latest_bar: Candle | None
    expected_latest_close_utc: UtcDatetime
    is_fresh: bool
    quality_status: Literal["ok", "failed"]
    dataset_ids: list[str]
    source: SourceRef

    @model_validator(mode="after")
    def _causal_and_fresh(self) -> Self:
        """
        Enforce causality and the freshness definition (R-07).

        Returns:
            MarketSnapshot: The validated snapshot.

        Raises:
            ValueError: If the latest bar closes after ``as_of_utc`` or ``is_fresh`` is wrong.
        """
        if self.latest_bar is not None and self.latest_bar.close_time_utc > self.as_of_utc:
            raise ValueError("latest_bar closes after as_of_utc (look-ahead)")
        fresh = (
            self.latest_bar is not None
            and self.latest_bar.close_time_utc == self.expected_latest_close_utc
        )
        if self.is_fresh != fresh:
            raise ValueError("is_fresh inconsistent with latest_bar")
        return self


class QualityIssue(DomainModel):
    """One data-quality finding."""

    check_id: str
    severity: Literal["error", "warning"]
    message: str
    detail: dict[str, str]


class DatasetManifest(DomainModel):
    """Immutable dataset description stored next to ``candles.parquet``."""

    schema_version: SchemaVersion
    dataset_id: str
    instrument_id: str
    timeframe: str
    source: SourceRef
    source_label: str
    row_count: int
    first_open_time_utc: UtcDatetime
    last_open_time_utc: UtcDatetime
    content_hash: str
    parquet_sha256: str
    quality_status: Literal["ok", "failed"]
    quality_issues: list[QualityIssue]
    gaps: list[str]
