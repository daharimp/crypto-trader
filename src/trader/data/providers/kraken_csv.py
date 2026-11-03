"""Kraken's downloadable OHLCVT history (support article 360047124832).

Files are headerless CSVs named ``<PAIR>_<minutes>.csv`` with the columns
``timestamp (unix seconds), open, high, low, close, volume, trades``. Rows exist only for
intervals with trades, so quiet periods appear as gaps (reported by DQ-06, never filled).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from ..frames import COLUMNS

MINUTES_TO_TIMEFRAME = {60: "1h", 240: "4h", 1440: "1d"}
_NAME = re.compile(r"^(?P<pair>[A-Z0-9]+)_(?P<minutes>\d+)\.csv$", re.IGNORECASE)


class KrakenCsvError(ValueError):
    """Raised for an unreadable file or an unsupported interval."""


def timeframe_from_name(path: Path) -> str:
    """
    Infer the timeframe from a Kraken file name such as ``XBTUSD_240.csv``.

    Args:
        path (Path): File path.

    Returns:
        str: ``1h``, ``4h``, or ``1d``.

    Raises:
        KrakenCsvError: If the name does not match or the interval is unsupported.
    """
    m = _NAME.match(path.name)
    if not m:
        raise KrakenCsvError(f"not a Kraken OHLCVT file name: {path.name} (expected PAIR_240.csv)")
    minutes = int(m.group("minutes"))
    if minutes not in MINUTES_TO_TIMEFRAME:
        raise KrakenCsvError(f"unsupported interval {minutes} minutes (use 60, 240, or 1440)")
    return MINUTES_TO_TIMEFRAME[minutes]


def read_kraken_ohlcvt(path: Path) -> pd.DataFrame:
    """
    Read a Kraken OHLCVT file into a raw candle frame (quality checks run in the store).

    Args:
        path (Path): Headerless Kraken CSV.

    Returns:
        pd.DataFrame: Frame with :data:`trader.data.frames.COLUMNS`.

    Raises:
        KrakenCsvError: If a row cannot be parsed.
    """
    rows = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            parts = line.strip().split(",")
            if not line.strip():
                continue
            if len(parts) < 6:
                raise KrakenCsvError(f"line {n}: expected at least 6 columns, got {len(parts)}")
            try:
                ts = datetime.fromtimestamp(int(float(parts[0])), tz=UTC)
                rows.append(
                    {
                        "open_time_utc": ts,
                        **{c: Decimal(v) for c, v in zip(COLUMNS[1:], parts[1:6], strict=True)},
                    }
                )
            except (InvalidOperation, ValueError, OverflowError) as exc:
                raise KrakenCsvError(f"line {n}: {exc}") from exc
    return pd.DataFrame(rows, columns=COLUMNS)
