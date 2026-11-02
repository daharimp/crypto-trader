"""Read-only public prices from Jupiter's Price API (ADR-024).

Only HTTP GET of a public endpoint; no wallet, no signing, no transaction building. The
response shape is parsed defensively: anything unexpected raises, so callers fail closed.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

PRICE_URL = "https://lite-api.jup.ag/price/v3"
Getter = Callable[[str], bytes]


class PriceUnavailableError(Exception):
    """Raised when a price is missing, malformed, or not positive."""


def _http_get(url: str) -> bytes:
    """
    Fetch a URL with a short timeout.

    Args:
        url (str): URL.

    Returns:
        bytes: Body.
    """
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed https URL)
        body: bytes = resp.read()
        return body


def fetch_prices(markets: dict[str, str], get: Getter = _http_get) -> dict[str, Decimal]:
    """
    Read USD prices for each market's token mint.

    Args:
        markets (dict[str, str]): Market name to token mint.
        get (Getter): HTTP getter (injectable for tests).

    Returns:
        dict[str, Decimal]: Market name to USD price.

    Raises:
        PriceUnavailableError: If any market has no valid price.
    """
    ids = ",".join(markets.values())
    try:
        data = json.loads(get(f"{PRICE_URL}?{urllib.parse.urlencode({'ids': ids})}"))
    except (OSError, ValueError) as exc:
        raise PriceUnavailableError(f"price request failed: {exc}") from exc
    # Reason: older API versions nest results under "data"; accept both shapes.
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        raise PriceUnavailableError("unexpected price response")
    out: dict[str, Decimal] = {}
    for market, mint in markets.items():
        entry = data.get(mint)
        raw = entry.get("usdPrice", entry.get("price")) if isinstance(entry, dict) else None
        try:
            price = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            raise PriceUnavailableError(f"{market}: no price") from None
        if not price.is_finite() or price <= 0:
            raise PriceUnavailableError(f"{market}: invalid price {raw}")
        out[market] = price
    return out
