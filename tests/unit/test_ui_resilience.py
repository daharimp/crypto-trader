"""ADR-050: the dashboard keeps answering when a price feed is slow, failing or abandoned."""

from __future__ import annotations

import socket
import threading
import time
import urllib.request

import pytest

from tests.perps_support import fixture_params
from trader.ui import server as ui_server
from trader.ui.server import Sources, serve


def _src(fetch: object) -> Sources:
    return Sources(lambda: {"sessions": []}, fetch, fixture_params, dict)  # type: ignore[arg-type]


def test_concurrent_requests_share_one_fetch() -> None:
    calls: list[str] = []

    def slow(sym: str, tf: str) -> list[list[float]]:
        calls.append(sym)
        time.sleep(0.2)
        return [[1.0]]

    src = _src(slow)
    threads = [threading.Thread(target=src.rows, args=("SOL/USD", "4h")) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == ["SOL/USD"]


def test_failed_refresh_serves_last_good_candles(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"fail": False}

    def fetch(sym: str, tf: str) -> list[list[float]]:
        if state["fail"]:
            raise OSError("kraken down")
        return [[42.0]]

    src = _src(fetch)
    assert src.rows("SOL/USD", "4h") == [[42.0]]
    monkeypatch.setattr(ui_server, "CACHE_SECONDS", -1)  # every call refreshes
    state["fail"] = True
    assert src.rows("SOL/USD", "4h") == [[42.0]]


def test_failure_with_nothing_cached_still_raises() -> None:
    def fetch(sym: str, tf: str) -> list[list[float]]:
        raise OSError("kraken down")

    with pytest.raises(OSError):
        _src(fetch).rows("SOL/USD", "4h")


def test_abandoned_connections_do_not_block_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_server, "REQUEST_TIMEOUT_SECONDS", 1)
    httpd = serve(_src(lambda s, t: []), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        # Clients that connect and never send a request (a phone that went to sleep).
        idle = [socket.create_connection(("127.0.0.1", port)) for _ in range(20)]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
            assert r.status == 200
        # The server hangs up on the idle ones instead of keeping a thread on each forever.
        idle[0].settimeout(5)
        assert idle[0].recv(1) == b""
        for s in idle:
            s.close()
    finally:
        httpd.shutdown()
