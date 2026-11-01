"""UTC time helpers and clocks (R-07, ADR-017).

All datetimes in the system are timezone-aware UTC. Naive datetimes are rejected.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Protocol

_TF_RE = re.compile(r"^(\d+)([mhd])$")
_UNIT = {"m": "minutes", "h": "hours", "d": "days"}


class NaiveTimestampError(ValueError):
    """Raised when a naive (timezone-less) datetime is supplied (NAIVE_TIMESTAMP)."""


def ensure_utc(value: datetime) -> datetime:
    """
    Validate that a datetime is timezone-aware and normalize it to UTC.

    Args:
        value (datetime): The datetime to check.

    Returns:
        datetime: The same instant expressed in UTC.

    Raises:
        NaiveTimestampError: If ``value`` has no timezone.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise NaiveTimestampError("NAIVE_TIMESTAMP")
    return value.astimezone(UTC)


def parse_utc(text: str) -> datetime:
    """
    Parse an ISO-8601 timestamp that must carry a timezone (``Z`` or an offset).

    Args:
        text (str): ISO-8601 text such as ``2024-01-01T00:00:00Z``.

    Returns:
        datetime: Timezone-aware UTC datetime.

    Raises:
        NaiveTimestampError: If the text has no timezone designator.
    """
    t = text.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return ensure_utc(datetime.fromisoformat(t))


def format_utc(value: datetime) -> str:
    """
    Format a UTC datetime as ``YYYY-MM-DDTHH:MM:SSZ`` (canonical form, §7.1).

    Args:
        value (datetime): Timezone-aware datetime.

    Returns:
        str: Canonical UTC text.
    """
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def timeframe_delta(timeframe: str) -> timedelta:
    """
    Convert a timeframe string (``1m``, ``1h``, ``4h``, ``1d``) to a timedelta.

    Args:
        timeframe (str): Timeframe label.

    Returns:
        timedelta: Bar duration.

    Raises:
        ValueError: If the label is not recognised.
    """
    m = _TF_RE.match(timeframe)
    if not m:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return timedelta(**{_UNIT[m.group(2)]: int(m.group(1))})


def is_aligned(value: datetime, timeframe: str) -> bool:
    """
    Check that a bar open time aligns to the UTC grid for the timeframe (DQ-03).

    Args:
        value (datetime): Bar open time (UTC).
        timeframe (str): Timeframe label.

    Returns:
        bool: True if aligned (e.g. 4h bars at 00, 04, ..., 20 UTC).
    """
    seconds = int(timeframe_delta(timeframe).total_seconds())
    epoch = int(ensure_utc(value).timestamp())
    return epoch % seconds == 0 and value.microsecond == 0


def next_utc_midnight(value: datetime) -> datetime:
    """
    Return the next 00:00 UTC strictly after ``value``.

    Args:
        value (datetime): Reference time.

    Returns:
        datetime: Next UTC midnight.
    """
    v = ensure_utc(value)
    return datetime(v.year, v.month, v.day, tzinfo=UTC) + timedelta(days=1)


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        ...


class WallClock:
    """Real wall-clock time in UTC."""

    def now(self) -> datetime:
        """
        Return the current wall-clock time.

        Returns:
            datetime: Current UTC time.
        """
        return datetime.now(UTC)


class SimulatedClock:
    """Deterministic clock driven by the backtest runner."""

    def __init__(self, start: datetime) -> None:
        """
        Create a simulated clock.

        Args:
            start (datetime): Initial UTC time.
        """
        self._now = ensure_utc(start)

    def now(self) -> datetime:
        """
        Return the simulated current time.

        Returns:
            datetime: Simulated UTC time.
        """
        return self._now

    def set(self, value: datetime) -> None:
        """
        Move the clock to ``value``. Time may not go backwards.

        Args:
            value (datetime): New UTC time.

        Raises:
            ValueError: If ``value`` is earlier than the current time.
        """
        v = ensure_utc(value)
        if v < self._now:
            raise ValueError("simulated clock cannot move backwards")
        self._now = v
