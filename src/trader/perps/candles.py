"""Polite candle fetching for a paper account that reads many markets (ADR-051).

Kraken limits public candle requests by IP address and currency pair, asks for about one
call a second, and refuses calls "for a few seconds" once a limit is hit (its API rate-limit
pages, read 2026-11-26). A ten-coin hourly account makes twenty requests a cycle, so they
are spaced out, and a refused or failed request is tried again a few times before the cycle
gives up. Read-only: no keys, no orders.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .session import CandleFetcher


@dataclass
class PacedFetcher:
    """A candle fetcher that spaces its requests and retries a failed one."""

    fetch: CandleFetcher
    # Least time between the start of two requests.
    spacing_s: float = 1.0
    # Wait before each retry; its length is the number of retries.
    backoff_s: tuple[float, ...] = (3.0, 8.0)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Refuse settings that would hammer the exchange or sleep a negative time."""
        if self.spacing_s < 0 or any(w < 0 for w in self.backoff_s):
            raise ValueError("spacing_s and backoff_s must not be negative")

    def _pace(self) -> None:
        if self._last is not None:
            gap = self.spacing_s - (self.clock() - self._last)
            if gap > 0:
                self.sleep(gap)
        self._last = self.clock()

    def __call__(self, symbol: str, timeframe: str) -> list[list[float]]:
        """
        Fetch candles, waiting first if the previous request was too recent.

        Args:
            symbol (str): e.g. ``BTC/USD``.
            timeframe (str): e.g. ``1h``.

        Returns:
            list[list[float]]: The wrapped fetcher's rows.

        Raises:
            Exception: Whatever the wrapped fetcher raised on the last attempt.
        """
        for wait in (*self.backoff_s, None):
            self._pace()
            try:
                return self.fetch(symbol, timeframe)
            except Exception:  # noqa: BLE001 - a read-only request; any failure may pass
                if wait is None:
                    raise
                self.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover
