"""Dashboard server: routes, read-only enforcement, error handling (ADR-026)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from tests.perps_support import fixture_params
from tests.unit.test_ui_data import _rows
from trader.ui.server import Sources, serve


@pytest.fixture
def base() -> Iterator[str]:
    calls: list[str] = []

    def fetch(sym: str, tf: str) -> list[list[float]]:
        calls.append(sym)
        return _rows(120)

    def fetch_some(sym: str, tf: str) -> list[list[float]]:
        if sym == "SUI/USD":
            raise OSError("one market down")
        return fetch(sym, tf)

    src = Sources(
        lambda: {"kill_switch": None, "sessions": []},
        fetch_some,
        fixture_params,
        lambda: {"SOL": 85.5},
    )
    httpd = serve(src, "127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_page_and_vendor_library_served(base: str) -> None:
    code, body = _get(base + "/")
    assert code == 200 and b"Trader Desk" in body and b"/vendor/lightweight-charts-4.2.0.js" in body
    code, body = _get(base + "/vendor/lightweight-charts-4.2.0.js")
    assert code == 200 and len(body) > 100_000
    assert _get(base + "/vendor/LIGHTWEIGHT-CHARTS-LICENSE.txt")[0] == 200


@pytest.mark.parametrize(
    ("path", "ctype", "marker"),
    [
        ("/app.css", "text/css", b".desk"),
        ("/desk.js", "text/javascript", b"window.Desk"),
        ("/widgets.js", "text/javascript", b"/api/watch"),
    ],
)
def test_workspace_assets_served_by_exact_name(
    base: str, path: str, ctype: str, marker: bytes
) -> None:
    with urllib.request.urlopen(base + path, timeout=10) as r:
        assert r.status == 200 and r.headers["Content-Type"].startswith(ctype)
        assert marker in r.read()
    page = _get(base + "/")[1]
    assert path.encode() in page


def test_watch_lists_markets_and_survives_one_failing(base: str) -> None:
    rows = json.loads(_get(base + "/api/watch")[1])
    assert [r["market"] for r in rows] == ["BTC", "ETH", "SOL", "XRP"]  # SUI's fetch failed
    assert all(r["trend"] in ("up", "down") and len(r["spark"]) > 2 for r in rows)
    assert _get(base + "/api/candles?market=XRP&timeframe=4h")[0] == 200


def test_api_routes(base: str) -> None:
    assert json.loads(_get(base + "/api/status")[1]) == {"kill_switch": None, "sessions": []}
    assert json.loads(_get(base + "/api/prices")[1]) == {"SOL": 85.5}
    c = json.loads(_get(base + "/api/candles?market=SOL&timeframe=4h")[1])
    assert len(c["candles"]) == 119
    p = json.loads(_get(base + "/api/perps?market=SOL&timeframe=4h")[1])
    assert "markers" in p


@pytest.mark.parametrize("path", ["/api/candles?market=DOGE", "/api/candles?timeframe=5m"])
def test_bad_inputs_rejected(base: str, path: str) -> None:
    assert _get(base + path)[0] == 400


@pytest.mark.parametrize(
    "path",
    ["/nope", "/vendor/../server.py", "/static/index.html", "/app.js", "/static/app.css"],
)
def test_unknown_paths_404(base: str, path: str) -> None:
    assert _get(base + path)[0] == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_writes_refused(base: str, method: str) -> None:
    req = urllib.request.Request(base + "/api/status", data=b"{}", method=method)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 405


def test_upstream_failure_is_502_not_crash() -> None:
    def boom(sym: str, tf: str) -> list[list[float]]:
        raise OSError("blocked")

    httpd = serve(Sources(lambda: {}, boom, fixture_params, lambda: {}), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    assert _get(base + "/api/candles?market=SOL")[0] == 502
    assert _get(base + "/api/status")[0] == 200  # still alive
    httpd.shutdown()


def test_default_bind_is_localhost() -> None:
    import inspect

    assert inspect.signature(serve).parameters["host"].default == "127.0.0.1"
