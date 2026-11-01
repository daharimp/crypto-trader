"""Candle provider interface (data-architecture.md §3)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trader.domain.candles import Candle


class CandleProvider(Protocol):
    """Read-only source of historical candles. Providers never place orders."""

    provider_id: str

    def fetch_candles(
        self, instrument_id: str, timeframe: str, start_utc: datetime, end_utc: datetime
    ) -> list[Candle]:
        """
        Return candles with ``start_utc <= open_time_utc < end_utc``.

        Args:
            instrument_id (str): Canonical instrument ID.
            timeframe (str): Timeframe label.
            start_utc (datetime): Inclusive start.
            end_utc (datetime): Exclusive end.

        Returns:
            list[Candle]: Candles in time order.
        """
        ...
