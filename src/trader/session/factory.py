"""Builds the live Kraken adapter from a compiled bundle (keys come from the environment)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from trader.execution.adapters.kraken_live import KrakenLiveAdapter
from trader.profiles.compiler import CompileBundle
from trader.universe.registry import Registry

from .config import SessionError, api_keys_from_env
from .market_data import kraken_symbols, make_kraken_client


def kraken_adapter_factory(
    bundle: CompileBundle, registry: Registry, client: Any | None = None
) -> KrakenLiveAdapter:
    """
    Create the live adapter. Requires an approved capital cap (UD-22) and API keys.

    Args:
        bundle (CompileBundle): Compiled live bundle.
        registry (Registry): Asset registry.
        client (Any | None): Pre-built client (tests); otherwise built from env keys.

    Returns:
        KrakenLiveAdapter: Adapter.

    Raises:
        SessionError: If the authorization or keys are missing.
    """
    auth = bundle.live
    if auth is None or auth.max_capital_usd.value == "TBD":
        raise SessionError(3, "live authorization incomplete (UD-22)")
    if client is None:
        key, secret = api_keys_from_env(auth.api_key_env["key"], auth.api_key_env["secret"])
        client = make_kraken_client(key, secret)
    fee = Decimal(bundle.compiled.cost_scenario.get("fee_rate_pct", "0.40"))
    return KrakenLiveAdapter(
        client, kraken_symbols(registry), Decimal(str(auth.max_capital_usd.value)), fee
    )
