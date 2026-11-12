"""Read-only dashboard HTTP server (ADR-026). GET only; binds to localhost by default."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlparse

from trader.perps.backtest import Bar

from .data import (
    MARKETS,
    TIMEFRAMES,
    Fetcher,
    candles_payload,
    fetch_bars,
    perps_payload,
    watch_payload,
)

# Reason: the only static files served, by exact name; no path from the request reaches disk.
STATIC = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/app.css": ("app.css", "text/css"),
    "/desk.js": ("desk.js", "text/javascript"),
    "/widgets.js": ("widgets.js", "text/javascript"),
    "/vendor/lightweight-charts-4.2.0.js": (
        "vendor/lightweight-charts-4.2.0.js",
        "text/javascript",
    ),
    "/vendor/LIGHTWEIGHT-CHARTS-LICENSE.txt": (
        "vendor/LIGHTWEIGHT-CHARTS-LICENSE.txt",
        "text/plain",
    ),
}

CACHE_SECONDS = 60


class Sources:
    """Everything the server reads, injectable for tests."""

    def __init__(
        self,
        status: Callable[[], dict[str, Any]],
        fetch: Fetcher,
        perps_params: Callable[[], Any],
        prices: Callable[[], dict[str, Any]],
    ) -> None:
        """
        Store the readers.

        Args:
            status (Callable): Returns the session snapshot.
            fetch (Fetcher): Public candle fetcher.
            perps_params (Callable): Loads approved perps parameters (may raise).
            prices (Callable): Returns live Jupiter prices.
        """
        self.status, self.fetch, self.perps_params, self.prices = (
            status,
            fetch,
            perps_params,
            prices,
        )
        self._cache: dict[tuple[str, str], tuple[float, list[list[float]]]] = {}

    def rows(self, symbol: str, timeframe: str) -> list[list[float]]:
        """Cached raw public candles (one fetch per symbol and timeframe per minute)."""
        key = (symbol, timeframe)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        rows = self.fetch(symbol, timeframe)
        self._cache[key] = (time.monotonic(), rows)
        return rows

    def bars(self, market: str, timeframe: str) -> list[Bar]:
        """Complete bars for one market, from the cached candles."""
        return fetch_bars(self.rows, market, timeframe)

    def watch(self) -> list[dict[str, Any]]:
        """Watchlist rows for every market; a market whose data fails is left out."""
        bars: dict[str, list[Bar]] = {}
        last: dict[str, float] = {}
        for market, symbol in MARKETS.items():
            try:
                rows = self.rows(symbol, "4h")
                bars[market] = fetch_bars(self.rows, market, "4h")
            except (OSError, ValueError, KeyError, StopIteration):
                continue
            if rows:
                # Reason: the last row is the still-forming candle; its close is the latest price.
                last[market] = float(rows[-1][4])
        return watch_payload(bars, last)


def make_handler(src: Sources) -> type[BaseHTTPRequestHandler]:
    """
    Build the request handler class bound to ``src``.

    Args:
        src (Sources): Data readers.

    Returns:
        type[BaseHTTPRequestHandler]: Handler class.
    """

    class Handler(BaseHTTPRequestHandler):
        server_version = "trader-ui"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return  # Reason: keep request lines out of the trading logs.

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            market = q.get("market", "SOL")
            tf = q.get("timeframe", "4h")
            try:
                if url.path in STATIC:
                    name, ctype = STATIC[url.path]
                    f = resources.files("trader.ui").joinpath(f"static/{name}")
                    self._send(200, f.read_bytes(), f"{ctype}; charset=utf-8")
                elif url.path == "/api/status":
                    self._json(200, src.status())
                elif url.path == "/api/watch":
                    self._json(200, src.watch())
                elif url.path in ("/api/candles", "/api/perps"):
                    if market not in MARKETS or tf not in TIMEFRAMES:
                        self._json(400, {"error": "unknown market or timeframe"})
                        return
                    bars = src.bars(market, tf)
                    if url.path == "/api/candles":
                        self._json(200, candles_payload(bars))
                    else:
                        self._json(200, perps_payload(src.perps_params, market, bars))
                elif url.path == "/api/prices":
                    self._json(200, src.prices())
                else:
                    self._json(404, {"error": "not found"})
            except Exception as exc:  # noqa: BLE001 - shown on the page, never crashes the server
                self._json(502, {"error": f"{type(exc).__name__}: {exc}"})

        def _refuse(self) -> None:
            self._json(405, {"error": "read-only dashboard: GET only"})

        do_POST = do_PUT = do_PATCH = do_DELETE = _refuse  # noqa: N815

    return Handler


def serve(src: Sources, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    """
    Create the server (call ``serve_forever`` on the result).

    Args:
        src (Sources): Data readers.
        host (str): Bind address.
        port (int): Port (0 picks a free one).

    Returns:
        ThreadingHTTPServer: Server.
    """
    return ThreadingHTTPServer((host, port), make_handler(src))
