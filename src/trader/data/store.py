"""Immutable, content-addressed dataset store (§7.5, data-architecture.md §7)."""

from __future__ import annotations

import json
import os
import stat
from decimal import Decimal
from pathlib import Path

import pandas as pd

from trader.common.clock import format_utc, parse_utc
from trader.common.hashing import sha256_hex, sha256_tag
from trader.common.paths import data_root
from trader.domain.candles import Candle
from trader.domain.market import DatasetManifest, SourceRef

from .frames import PRICE_COLS, canonical_text, candles_to_frame, norm_decimal
from .quality import QualityReport, run_quality_checks


class DataQualityError(ValueError):
    """Raised when error-severity quality checks fail (``DATA_QUALITY_FAILED``, exit 2)."""

    def __init__(self, report: QualityReport) -> None:
        """
        Store the failing report.

        Args:
            report (QualityReport): Report with errors.
        """
        self.report = report
        msgs = "; ".join(f"{i.check_id} {i.message}" for i in report.errors)
        super().__init__(f"DATA_QUALITY_FAILED: {msgs}")


class DatasetIntegrityError(ValueError):
    """Raised when stored data no longer matches its manifest (exit 4)."""


class DatasetNotFoundError(KeyError):
    """Raised for an unknown dataset ID."""


class DatasetStore:
    """Writes and verifies datasets under ``data/datasets/<id>/``."""

    def __init__(self, root: Path | None = None) -> None:
        """
        Create a store.

        Args:
            root (Path | None): Datasets directory; defaults to ``data/datasets``.
        """
        self.root = root or (data_root() / "datasets")

    def create(
        self,
        candles: list[Candle],
        instrument_id: str,
        timeframe: str,
        source: SourceRef,
        source_label: str,
    ) -> DatasetManifest:
        """
        Create a dataset from candles (idempotent).

        Args:
            candles (list[Candle]): Candles.
            instrument_id (str): Instrument.
            timeframe (str): Timeframe.
            source (SourceRef): Provenance.
            source_label (str): Label included in the dataset identity.

        Returns:
            DatasetManifest: New or existing manifest.
        """
        return self.create_from_frame(
            candles_to_frame(candles), instrument_id, timeframe, source, source_label
        )

    def create_from_frame(
        self,
        df: pd.DataFrame,
        instrument_id: str,
        timeframe: str,
        source: SourceRef,
        source_label: str,
    ) -> DatasetManifest:
        """
        Quality-check a raw frame and store it. Existing IDs are returned unchanged.

        Args:
            df (pd.DataFrame): Raw candle frame.
            instrument_id (str): Instrument.
            timeframe (str): Timeframe.
            source (SourceRef): Provenance.
            source_label (str): Source label.

        Returns:
            DatasetManifest: Manifest.

        Raises:
            DataQualityError: If any error-severity check fails (nothing is written).
        """
        report = run_quality_checks(df, timeframe, source.retrieved_at_utc)
        if not report.ok:
            raise DataQualityError(report)
        clean = report.frame
        text = canonical_text(clean, instrument_id, timeframe, source_label)
        dataset_id = "ds-" + sha256_hex(text)[:16]
        ddir = self.root / dataset_id
        if (ddir / "manifest.json").exists():
            return self._read_manifest(dataset_id)
        ddir.mkdir(parents=True, exist_ok=True)
        pq = ddir / "candles.parquet"
        out = pd.DataFrame(
            {
                "open_time_utc": [format_utc(t) for t in clean["open_time_utc"]],
                **{c: [norm_decimal(v) for v in clean[c]] for c in PRICE_COLS},
            }
        )
        out.to_parquet(pq, index=False)
        manifest = DatasetManifest(
            schema_version="1.0.0",
            dataset_id=dataset_id,
            instrument_id=instrument_id,
            timeframe=timeframe,
            source=source,
            source_label=source_label,
            row_count=len(clean),
            first_open_time_utc=clean["open_time_utc"].iloc[0],
            last_open_time_utc=clean["open_time_utc"].iloc[-1],
            content_hash=sha256_tag(text),
            parquet_sha256=sha256_tag(pq.read_bytes()),
            quality_status="ok",
            quality_issues=report.issues,
            gaps=report.gaps,
        )
        mf = ddir / "manifest.json"
        mf.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        # Reason: datasets are immutable; read-only files make accidental edits fail loudly.
        for f in (pq, mf):
            os.chmod(f, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return manifest

    def _read_manifest(self, dataset_id: str) -> DatasetManifest:
        """
        Read a manifest.

        Args:
            dataset_id (str): Dataset ID.

        Returns:
            DatasetManifest: Manifest.

        Raises:
            DatasetNotFoundError: If missing.
        """
        mf = self.root / dataset_id / "manifest.json"
        if not mf.exists():
            raise DatasetNotFoundError(dataset_id)
        return DatasetManifest.model_validate(json.loads(mf.read_text(encoding="utf-8")))

    def load(self, dataset_id: str) -> tuple[DatasetManifest, pd.DataFrame]:
        """
        Load a dataset and re-verify its hashes.

        Args:
            dataset_id (str): Dataset ID.

        Returns:
            tuple[DatasetManifest, pd.DataFrame]: Manifest and candle frame.

        Raises:
            DatasetIntegrityError: If the file or content hash does not match.
        """
        manifest = self._read_manifest(dataset_id)
        pq = self.root / dataset_id / "candles.parquet"
        if sha256_tag(pq.read_bytes()) != manifest.parquet_sha256:
            raise DatasetIntegrityError(f"DATASET_INTEGRITY_FAILED: {dataset_id} file hash")
        raw = pd.read_parquet(pq)
        df = pd.DataFrame(
            {
                "open_time_utc": [parse_utc(t) for t in raw["open_time_utc"]],
                **{c: [Decimal(v) for v in raw[c]] for c in PRICE_COLS},
            }
        )
        text = canonical_text(df, manifest.instrument_id, manifest.timeframe, manifest.source_label)
        if sha256_tag(text) != manifest.content_hash or "ds-" + sha256_hex(text)[:16] != dataset_id:
            raise DatasetIntegrityError(f"DATASET_INTEGRITY_FAILED: {dataset_id} content hash")
        return manifest, df

    def list(self) -> list[DatasetManifest]:
        """
        List all datasets.

        Returns:
            list[DatasetManifest]: Manifests sorted by ID.
        """
        if not self.root.exists():
            return []
        return [
            self._read_manifest(d.name)
            for d in sorted(self.root.iterdir())
            if (d / "manifest.json").exists()
        ]
