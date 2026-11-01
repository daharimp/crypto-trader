"""Candle frame helpers: the in-memory representation used by checks and the store.

A candle frame is a pandas DataFrame with columns ``open_time_utc`` (Python ``datetime``)
and ``open, high, low, close, volume`` (``Decimal``). Exact Decimals are kept in object
columns so hashes and fills are reproducible (ADR-017).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from trader.common.clock import format_utc, timeframe_delta
from trader.domain.candles import Candle

PRICE_COLS = ["open", "high", "low", "close", "volume"]
COLUMNS = ["open_time_utc", *PRICE_COLS]


def norm_decimal(value: Decimal) -> str:
    """
    Normalize a Decimal to plain text without exponent or trailing zeros.

    Args:
        value (Decimal): Number.

    Returns:
        str: e.g. ``"30000"`` for ``Decimal("30000.00")``.
    """
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


def columns(df: pd.DataFrame, name: str) -> list[Any]:
    """
    Return a frame column as a plain Python list.

    Args:
        df (pd.DataFrame): Frame.
        name (str): Column name.

    Returns:
        list[Any]: Column values.
    """
    values: list[Any] = df[name].tolist()
    return values


def candles_to_frame(candles: list[Candle]) -> pd.DataFrame:
    """
    Convert candles to a candle frame.

    Args:
        candles (list[Candle]): Candles.

    Returns:
        pd.DataFrame: Frame with :data:`COLUMNS`.
    """
    rows = [
        {
            "open_time_utc": c.open_time_utc,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def frame_to_candles(df: pd.DataFrame, timeframe: str) -> list[Candle]:
    """
    Convert a (quality-checked) frame to candles.

    Args:
        df (pd.DataFrame): Candle frame.
        timeframe (str): Timeframe label.

    Returns:
        list[Candle]: Candles in frame order.
    """
    delta = timeframe_delta(timeframe)
    out: list[Candle] = []
    for t, o, h, lo, c, v in zip(*(columns(df, k) for k in COLUMNS), strict=True):
        out.append(
            Candle(
                open_time_utc=t, close_time_utc=t + delta, open=o, high=h, low=lo, close=c, volume=v
            )
        )
    return out


def canonical_text(df: pd.DataFrame, instrument_id: str, timeframe: str, source_label: str) -> str:
    """
    Build the canonical text that defines a dataset's identity (§7.5).

    Args:
        df (pd.DataFrame): Candle frame (sorted, checked).
        instrument_id (str): Instrument.
        timeframe (str): Timeframe.
        source_label (str): Source label.

    Returns:
        str: Canonical text.
    """
    parts = [f"{instrument_id}\n{timeframe}\n{source_label}\n"]
    cols = [columns(df, c) for c in PRICE_COLS]
    for i, t in enumerate(columns(df, "open_time_utc")):
        vals = ",".join(norm_decimal(col[i]) for col in cols)
        parts.append(f"{format_utc(t)},{vals}\n")
    return "".join(parts)
