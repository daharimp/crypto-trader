"""Public Kraken market data for forward sessions (UD-20; no API key needed)."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from trader.common.hashing import sha256_hex
from trader.data.frames import COLUMNS, canonical_text, frame_to_candles
from trader.data.quality import run_quality_checks
from trader.domain.candles import Candle
from trader.domain.market import DatasetManifest, SourceRef
from trader.universe.registry import Registry

VENUE = "kraken"
# Reason: Kraken's OHLC endpoint returns at most the latest 720 candles per timeframe.
MAX_CANDLES = 720


class MarketDataError(RuntimeError):
    """Raised when candles cannot be fetched or fail error-level quality checks."""


def make_kraken_client(api_key: str | None = None, api_secret: str | None = None) -> Any:
    """
    Build a ``ccxt.kraken`` client. Without keys it can only read public data.

    Args:
        api_key (str | None): API key (live only; read from the environment by the caller).
        api_secret (str | None): API secret.

    Returns:
        Any: ccxt client.

    Raises:
        MarketDataError: If ``ccxt`` is not installed.
    """
    try:
        ccxt = importlib.import_module("ccxt")
    except ModuleNotFoundError as exc:
        raise MarketDataError("ccxt is not installed: run `uv sync --extra ccxt`") from exc
    client = ccxt.kraken({"enableRateLimit": True})
    if api_key and api_secret:
        # Reason: credentials are set as attributes, never written to config or logs.
        client.apiKey, client.secret = api_key, api_secret
    return client


def kraken_symbols(registry: Registry) -> dict[str, str]:
    """
    Instrument ID -> Kraken ccxt symbol from the asset registry (``kraken:*`` mappings).

    Args:
        registry (Registry): Asset registry.

    Returns:
        dict[str, str]: Symbol map.
    """
    return {
        m.instrument_id: m.venue_symbol
        for m in registry.data.market_symbol_map
        if m.venue_id == VENUE
    }


class KrakenMarketData:
    """Fetches complete candles and the exchange clock."""

    def __init__(self, client: Any, symbols: dict[str, str]) -> None:
        """
        Create the data source.

        Args:
            client (Any): ccxt client (public access is enough).
            symbols (dict[str, str]): Instrument -> ccxt symbol.
        """
        self.client = client
        self.symbols = symbols

    def server_time(self) -> datetime:
        """
        Kraken server time (for the clock-skew check, UD-17).

        Returns:
            datetime: UTC time.
        """
        return datetime.fromtimestamp(int(self.client.fetch_time()) / 1000, tz=UTC)

    def candles(self, instrument_id: str, timeframe: str, now: datetime) -> list[Candle]:
        """
        Latest complete candles; the still-forming candle is dropped (DQ-11).

        Args:
            instrument_id (str): Instrument.
            timeframe (str): ``4h`` or ``1d``.
            now (datetime): Retrieval time.

        Returns:
            list[Candle]: Candles, oldest first.

        Raises:
            MarketDataError: On fetch failure or error-level quality problems.
        """
        sym = self.symbols.get(instrument_id)
        if sym is None:
            raise MarketDataError(f"no Kraken symbol for {instrument_id}")
        try:
            rows = self.client.fetch_ohlcv(sym, timeframe, None, MAX_CANDLES)
        except Exception as exc:  # noqa: BLE001 - surfaced as stale data, never a crash
            raise MarketDataError(f"fetch_ohlcv {sym} {timeframe}: {exc}") from exc
        frame = pd.DataFrame(
            [
                {
                    "open_time_utc": datetime.fromtimestamp(r[0] / 1000, tz=UTC),
                    **{k: Decimal(str(v)) for k, v in zip(COLUMNS[1:], r[1:6], strict=True)},
                }
                for r in rows
            ],
            columns=COLUMNS,
        )
        rep = run_quality_checks(frame, timeframe, now)
        if not rep.ok:
            raise MarketDataError("; ".join(f"{i.check_id} {i.message}" for i in rep.errors))
        return frame_to_candles(rep.frame, timeframe)


def live_manifest(
    instrument_id: str, timeframe: str, candles: list[Candle], now: datetime
) -> DatasetManifest:
    """
    An in-memory manifest for fetched candles (forward sessions keep no dataset files).

    Args:
        instrument_id (str): Instrument.
        timeframe (str): Timeframe.
        candles (list[Candle]): Candles (non-empty).
        now (datetime): Retrieval time.

    Returns:
        DatasetManifest: Manifest whose ID is the content hash of the candles.
    """
    from trader.data.frames import candles_to_frame

    text = canonical_text(candles_to_frame(candles), instrument_id, timeframe, VENUE)
    return DatasetManifest(
        schema_version="1.0.0",
        dataset_id="live-" + sha256_hex(text)[:16],
        instrument_id=instrument_id,
        timeframe=timeframe,
        source=SourceRef(provider_id="ccxt_public", venue_id=VENUE, retrieved_at_utc=now),
        source_label=f"{VENUE}:live",
        row_count=len(candles),
        first_open_time_utc=candles[0].open_time_utc,
        last_open_time_utc=candles[-1].open_time_utc,
        content_hash="sha256:" + sha256_hex(text),
        parquet_sha256="none",
        quality_status="ok",
        quality_issues=[],
        gaps=[],
    )
