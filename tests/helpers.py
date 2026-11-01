"""Hand-built candle helpers for exact-value tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd

from trader.common.clock import timeframe_delta
from trader.data.frames import COLUMNS
from trader.domain.candles import Candle

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def candle(t: datetime, o: str, h: str, lo: str, c: str, v: str = "100", tf: str = "4h") -> Candle:
    """Build one candle."""
    return Candle(
        open_time_utc=t,
        close_time_utc=t + timeframe_delta(tf),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(lo),
        close=Decimal(c),
        volume=Decimal(v),
    )


def series(
    closes: list[Decimal | str | int], start: datetime = T0, tf: str = "4h", volume: str = "100"
) -> list[Candle]:
    """Build candles whose open is the previous close and high/low bracket the body."""
    out: list[Candle] = []
    prev = Decimal(str(closes[0]))
    delta = timeframe_delta(tf)
    for i, c in enumerate(closes):
        c = Decimal(str(c))
        hi, lo = max(prev, c) + 1, min(prev, c) - 1
        out.append(candle(start + i * delta, str(prev), str(hi), str(lo), str(c), volume, tf))
        prev = c
    return out


def frame(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    """Build a raw candle frame from tuples (time, o, h, l, c, v)."""
    return pd.DataFrame(
        [
            {
                k: (Decimal(str(v)) if i else v)
                for i, (k, v) in enumerate(zip(COLUMNS, r, strict=False))
            }
            for r in rows
        ],
        columns=COLUMNS,
    )


def hours(n: int) -> timedelta:
    """Shorthand for a timedelta of ``n`` hours."""
    return timedelta(hours=n)
