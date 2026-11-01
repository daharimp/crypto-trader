"""Optional public OHLCV download via ``ccxt`` (extra ``ccxt``).

Only the unauthenticated ``fetch_ohlcv`` endpoint is used. No API keys are read or stored,
and ``ccxt`` is imported only when this provider is used (tests mock it).
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trader.common.clock import ensure_utc, timeframe_delta
from trader.domain.candles import Candle

_PAGE = 500


class CcxtPublicCandleProvider:
    """Public OHLCV candles from an explicitly named exchange."""

    provider_id = "ccxt_public"

    def __init__(self, exchange: str, symbol: str, client: Any | None = None) -> None:
        """
        Configure the provider.

        Args:
            exchange (str): ccxt exchange ID (required; no default venue, UD-20).
            symbol (str): Venue symbol, e.g. ``BTC/USD``.
            client (Any | None): Pre-built client (tests inject a mock).
        """
        self.exchange = exchange
        self.venue_id = exchange
        self.symbol = symbol
        self._client = client

    def _get_client(self) -> Any:
        """
        Create the public ccxt client lazily (no credentials).

        Returns:
            Any: ccxt exchange instance.
        """
        if self._client is None:
            ccxt = importlib.import_module("ccxt")
            self._client = getattr(ccxt, self.exchange)({"enableRateLimit": True})
        return self._client

    def fetch_candles(
        self, instrument_id: str, timeframe: str, start_utc: datetime, end_utc: datetime
    ) -> list[Candle]:
        """
        Page through public OHLCV data.

        Args:
            instrument_id (str): Canonical instrument (labels only).
            timeframe (str): Timeframe.
            start_utc (datetime): Inclusive start.
            end_utc (datetime): Exclusive end.

        Returns:
            list[Candle]: Candles in time order (dedupe and checks happen in the store).
        """
        client = self._get_client()
        delta = timeframe_delta(timeframe)
        since = int(ensure_utc(start_utc).timestamp() * 1000)
        end_ms = int(ensure_utc(end_utc).timestamp() * 1000)
        out: list[Candle] = []
        while since < end_ms:
            rows = client.fetch_ohlcv(self.symbol, timeframe, since, _PAGE)
            if not rows:
                break
            for ts, o, h, lo, c, v in rows:
                if ts >= end_ms:
                    break
                t = datetime.fromtimestamp(ts / 1000, tz=UTC)
                out.append(
                    Candle(
                        open_time_utc=t,
                        close_time_utc=t + delta,
                        open=Decimal(str(o)),
                        high=Decimal(str(h)),
                        low=Decimal(str(lo)),
                        close=Decimal(str(c)),
                        volume=Decimal(str(v)),
                    )
                )
            next_since = int(rows[-1][0]) + int(delta.total_seconds() * 1000)
            if next_since <= since:
                break
            since = next_since
        return out
