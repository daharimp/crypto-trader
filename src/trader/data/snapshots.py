"""Point-in-time market snapshots and windows (causal access only, R-07)."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from trader.common.clock import timeframe_delta
from trader.domain.candles import Candle
from trader.domain.market import DatasetManifest, MarketSnapshot, SourceRef

from .frames import frame_to_candles

_NO_SOURCE = SourceRef(provider_id="none", venue_id="none", retrieved_at_utc=None)


@dataclass
class _Series:
    """Candles for one instrument with a close-time index."""

    manifest: DatasetManifest
    candles: list[Candle]
    close_times: list[datetime]
    by_open: dict[datetime, Candle]


class SnapshotBuilder:
    """Serves snapshots and windows that only contain candles closed by ``t``."""

    def __init__(self, timeframe: str) -> None:
        """
        Create an empty builder.

        Args:
            timeframe (str): Decision timeframe.
        """
        self.timeframe = timeframe
        self.delta = timeframe_delta(timeframe)
        self._series: dict[str, _Series] = {}

    def add(self, manifest: DatasetManifest, df: pd.DataFrame) -> None:
        """
        Register a verified dataset.

        Args:
            manifest (DatasetManifest): Manifest.
            df (pd.DataFrame): Candle frame.
        """
        candles = frame_to_candles(df, manifest.timeframe)
        self._series[manifest.instrument_id] = _Series(
            manifest=manifest,
            candles=candles,
            close_times=[c.close_time_utc for c in candles],
            by_open={c.open_time_utc: c for c in candles},
        )

    @property
    def instruments(self) -> list[str]:
        """
        Registered instruments, sorted.

        Returns:
            list[str]: Instrument IDs.
        """
        return sorted(self._series)

    def manifest(self, instrument_id: str) -> DatasetManifest:
        """
        Return the manifest for an instrument.

        Args:
            instrument_id (str): Instrument.

        Returns:
            DatasetManifest: Manifest.
        """
        return self._series[instrument_id].manifest

    def bar_at_open(self, instrument_id: str, open_time: datetime) -> Candle | None:
        """
        Return the bar opening at ``open_time`` (used by the simulator for fills).

        Args:
            instrument_id (str): Instrument.
            open_time (datetime): Bar open time.

        Returns:
            Candle | None: Bar, or None if missing.
        """
        s = self._series.get(instrument_id)
        return s.by_open.get(open_time) if s else None

    def history(self, instrument_id: str, t: datetime) -> list[Candle]:
        """
        Return all candles with ``close_time_utc <= t``.

        Args:
            instrument_id (str): Instrument.
            t (datetime): Decision time.

        Returns:
            list[Candle]: Closed candles.
        """
        s = self._series.get(instrument_id)
        if s is None:
            return []
        return s.candles[: bisect_right(s.close_times, t)]

    def window(self, instrument_id: str, t: datetime, bars: int) -> list[Candle]:
        """
        Return the last ``bars`` candles with ``close_time_utc <= t``.

        Args:
            instrument_id (str): Instrument.
            t (datetime): Decision time.
            bars (int): Maximum number of bars.

        Returns:
            list[Candle]: Window (oldest first).
        """
        s = self._series.get(instrument_id)
        if s is None:
            return []
        end = bisect_right(s.close_times, t)
        return s.candles[max(0, end - bars) : end]

    def snapshot(
        self, instrument_id: str, t: datetime, cycle_id: str, snapshot_id: str
    ) -> MarketSnapshot:
        """
        Build the snapshot at decision time ``t``.

        Args:
            instrument_id (str): Instrument.
            t (datetime): Decision time (a bar close).
            cycle_id (str): Cycle ID.
            snapshot_id (str): Snapshot ID.

        Returns:
            MarketSnapshot: Fresh if the candle closing exactly at ``t`` exists.
        """
        s = self._series.get(instrument_id)
        window = self.window(instrument_id, t, 1)
        latest = window[-1] if window else None
        fresh = latest is not None and latest.close_time_utc == t
        return MarketSnapshot(
            schema_version="1.0.0",
            snapshot_id=snapshot_id,
            cycle_id=cycle_id,
            instrument_id=instrument_id,
            timeframe=self.timeframe,
            as_of_utc=t,
            latest_bar=latest,
            expected_latest_close_utc=t,
            is_fresh=fresh,
            quality_status="ok" if s and s.manifest.quality_status == "ok" else "failed",
            dataset_ids=[s.manifest.dataset_id] if s else [],
            source=s.manifest.source if s else _NO_SOURCE,
        )
