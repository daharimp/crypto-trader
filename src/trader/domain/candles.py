"""Candle contract."""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import model_validator

from .common import DomainModel, UtcDatetime


class Candle(DomainModel):
    """One OHLCV bar labelled by its UTC open time (R-07)."""

    open_time_utc: UtcDatetime
    close_time_utc: UtcDatetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @model_validator(mode="after")
    def _check_ohlc(self) -> Self:
        """
        Enforce OHLC consistency (DQ-07).

        Returns:
            Candle: The validated candle.

        Raises:
            ValueError: If prices are not positive or the OHLC relations do not hold.
        """
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC_NON_POSITIVE")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC_INCONSISTENT")
        if self.volume < 0:
            raise ValueError("VOLUME_NEGATIVE")
        if self.close_time_utc <= self.open_time_utc:
            raise ValueError("CLOSE_BEFORE_OPEN")
        return self
