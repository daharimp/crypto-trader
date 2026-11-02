"""Jupiter price parsing fails closed (ADR-024). No network: a fake getter."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from trader.perps.prices import PRICE_URL, PriceUnavailableError, fetch_prices

MKTS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "ETH": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
}


def _getter(payload: object):  # type: ignore[no-untyped-def]
    seen: list[str] = []

    def get(url: str) -> bytes:
        seen.append(url)
        return json.dumps(payload).encode()

    return get, seen


def test_v3_shape() -> None:
    get, seen = _getter({MKTS["SOL"]: {"usdPrice": 150.25}, MKTS["ETH"]: {"usdPrice": "3000.1"}})
    out = fetch_prices(MKTS, get)
    assert out == {"SOL": Decimal("150.25"), "ETH": Decimal("3000.1")}
    assert seen[0].startswith(PRICE_URL)


def test_data_wrapped_shape() -> None:
    get, _ = _getter({"data": {MKTS["SOL"]: {"price": "1"}, MKTS["ETH"]: {"price": "2"}}})
    assert fetch_prices(MKTS, get)["ETH"] == Decimal(2)


@pytest.mark.parametrize(
    "payload",
    [
        {MKTS["SOL"]: {"usdPrice": 1}},
        {MKTS["SOL"]: {"usdPrice": 0}, MKTS["ETH"]: {"usdPrice": 1}},
        {MKTS["SOL"]: {"usdPrice": "nan"}, MKTS["ETH"]: {"usdPrice": 1}},
        [1, 2],
    ],
)
def test_bad_payloads_fail_closed(payload: object) -> None:
    get, _ = _getter(payload)
    with pytest.raises(PriceUnavailableError):
        fetch_prices(MKTS, get)


def test_network_error_fails_closed() -> None:
    def boom(url: str) -> bytes:
        raise OSError("blocked")

    with pytest.raises(PriceUnavailableError):
        fetch_prices(MKTS, boom)
