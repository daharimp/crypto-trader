"""ADR-055: the dashboard shows the ten-coin paper account and prices for all its coins."""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from tests.perps_support import fixture_params
from trader.ui import server as ui_server
from trader.ui.server import Sources, serve

TOP10 = ["BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "HYPE", "ZEC", "DOGE", "LINK"]


def _row(close: float) -> list[float]:
    return [1_764_000_000.0, close, close, close, close, close, 1.0, 1.0]


def _src(fetch: Any, acct: dict[str, Any] | None = None, markets: list[str] = TOP10) -> Sources:
    return Sources(
        lambda: {"sessions": []},
        fetch,
        fixture_params,
        dict,
        lambda: None,
        lambda: None,
        lambda: acct,
        lambda: markets,
    )


def _get(base: str, path: str) -> Any:
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return json.loads(r.read()) if path.startswith("/api") else r.read()


@pytest.fixture
def served() -> Iterator[Any]:
    started: list[Any] = []

    def start(src: Sources) -> str:
        httpd = serve(src, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for h in started:
        h.shutdown()


def test_prices_for_every_top10_coin(served: Any) -> None:
    calls: list[str] = []

    def fetch(sym: str, tf: str) -> list[list[float]]:
        calls.append(f"{sym} {tf}")
        return [_row(1.0), _row(float(len(calls)))]

    base = served(_src(fetch))
    prices = _get(base, "/api/top10-prices")
    assert sorted(prices) == sorted(TOP10)
    # The latest (still-forming) candle's close, one fetch per coin, then cached.
    assert prices["BTC"] == 1.0 and prices["LINK"] == 10.0
    _get(base, "/api/top10-prices")
    assert len(calls) == 10 and all(c.endswith(" 4h") for c in calls)


def test_one_coin_down_leaves_the_others(served: Any) -> None:
    def fetch(sym: str, tf: str) -> list[list[float]]:
        if sym == "HYPE/USD":
            raise OSError("pair unavailable")
        return [_row(5.0)]

    prices = _get(served(_src(fetch)), "/api/top10-prices")
    assert "HYPE" not in prices and prices["ZEC"] == 5.0 and len(prices) == 9


def test_stale_price_kept_when_kraken_fails(served: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"down": False}

    def fetch(sym: str, tf: str) -> list[list[float]]:
        if state["down"]:
            raise OSError("kraken down")
        return [_row(7.0)]

    base = served(_src(fetch, markets=["DOGE"]))
    assert _get(base, "/api/top10-prices") == {"DOGE": 7.0}
    monkeypatch.setattr(ui_server, "CACHE_SECONDS", -1)
    state["down"] = True
    assert _get(base, "/api/top10-prices") == {"DOGE": 7.0}


def test_unknown_coin_is_never_requested(served: Any) -> None:
    calls: list[str] = []

    def fetch(sym: str, tf: str) -> list[list[float]]:
        calls.append(sym)
        return [_row(1.0)]

    assert _get(served(_src(fetch, markets=["NOPE", "BTC"])), "/api/top10-prices") == {"BTC": 1.0}
    assert calls == ["BTC/USD"]


def test_top10_account_route_and_page(served: Any) -> None:
    acct = {"equity_usd": "2490", "positions": [], "trades": []}
    base = served(_src(lambda s, t: [], acct))
    assert _get(base, "/api/perps-top10") == {"running": True, **acct}
    assert _get(served(_src(lambda s, t: [])), "/api/perps-top10") == {"running": False}
    page, views = _get(base, "/"), _get(base, "/views.js")
    assert b'data-v="top10"' in page
    assert b"/api/perps-top10" in views and b"/api/top10-prices" in views
