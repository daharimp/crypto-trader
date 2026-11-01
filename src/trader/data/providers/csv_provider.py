"""CSV candle import (columns ``open_time_utc,open,high,low,close,volume``)."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from trader.common.clock import ensure_utc
from trader.domain.candles import Candle

from ..frames import COLUMNS, frame_to_candles
from ..quality import run_quality_checks


class CsvFormatError(ValueError):
    """Raised when the CSV cannot be parsed."""


def _parse_time(text: str) -> datetime:
    """
    Parse ISO-8601 (timezone required) or integer epoch milliseconds.

    Naive ISO text is returned naive so DQ-02 can report ``NAIVE_TIMESTAMP``.

    Args:
        text (str): Cell text.

    Returns:
        datetime: Parsed datetime (naive only if the text had no timezone).
    """
    t = text.strip()
    if t.isdigit():
        return datetime.fromtimestamp(int(t) / 1000, tz=UTC)
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t)


class CsvCandleProvider:
    """Reads candles from a local CSV file."""

    provider_id = "csv"
    venue_id = "csv"

    def __init__(self, path: Path) -> None:
        """
        Configure the provider.

        Args:
            path (Path): CSV file path.
        """
        self.path = path

    def read_frame(self) -> pd.DataFrame:
        """
        Read the CSV into a raw candle frame (no quality checks).

        Returns:
            pd.DataFrame: Raw frame.

        Raises:
            CsvFormatError: If columns are missing or cells cannot be parsed.
        """
        with self.path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or any(c not in reader.fieldnames for c in COLUMNS):
                raise CsvFormatError(f"CSV must have columns {','.join(COLUMNS)}")
            rows = []
            for i, row in enumerate(reader, start=2):
                try:
                    rows.append(
                        {
                            "open_time_utc": _parse_time(row["open_time_utc"]),
                            **{c: Decimal(row[c]) for c in COLUMNS[1:]},
                        }
                    )
                except (InvalidOperation, ValueError) as exc:
                    raise CsvFormatError(f"line {i}: {exc}") from exc
        return pd.DataFrame(rows, columns=COLUMNS)

    def fetch_candles(
        self, instrument_id: str, timeframe: str, start_utc: datetime, end_utc: datetime
    ) -> list[Candle]:
        """
        Return quality-checked candles in ``[start_utc, end_utc)``.

        Args:
            instrument_id (str): Instrument (labels only).
            timeframe (str): Timeframe.
            start_utc (datetime): Inclusive start.
            end_utc (datetime): Exclusive end.

        Returns:
            list[Candle]: Candles.

        Raises:
            ValueError: If quality checks fail.
        """
        rep = run_quality_checks(self.read_frame(), timeframe, None)
        if not rep.ok:
            raise ValueError("DATA_QUALITY_FAILED: " + "; ".join(i.message for i in rep.errors))
        s, e = ensure_utc(start_utc), ensure_utc(end_utc)
        return [c for c in frame_to_candles(rep.frame, timeframe) if s <= c.open_time_utc < e]
