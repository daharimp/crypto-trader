"""Live preflight (``trader live preflight``): checks keys and order shapes, never trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from trader.execution.adapters.kraken_live import KrakenLiveAdapter

from .market_data import KrakenMarketData


@dataclass
class Check:
    """One preflight result."""

    name: str
    ok: bool
    detail: str


def _classify(exc: Exception, funds_ok: bool) -> tuple[bool, str]:
    """
    Interpret a ccxt error from a validate-only order.

    Args:
        exc (Exception): Error raised by ccxt.
        funds_ok (bool): Treat insufficient funds as a pass (the key and shape were accepted).

    Returns:
        tuple[bool, str]: Pass flag and explanation.
    """
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDenied", "AccountSuspended"):
        return False, f"{name}: the API key lacks permission or is invalid ({exc})"
    if name == "InsufficientFunds":
        return funds_ok, f"InsufficientFunds (authenticated; order shape accepted): {exc}"
    return False, f"{name}: {exc}"


def run_preflight(
    adapter: KrakenLiveAdapter,
    data: KrakenMarketData,
    now: datetime,
    skew_tolerance_s: Decimal = Decimal(5),
) -> list[Check]:
    """
    Run every preflight check. Uses Kraken's validate-only flag, so no order is placed.

    Args:
        adapter (KrakenLiveAdapter): Live adapter built with the owner's key.
        data (KrakenMarketData): Public market data.
        now (datetime): Local time.
        skew_tolerance_s (Decimal): Allowed clock skew (UD-17).

    Returns:
        list[Check]: Results, in order.
    """
    out: list[Check] = []
    try:
        skew = abs((data.server_time() - now).total_seconds())
        out.append(Check("clock skew", Decimal(str(skew)) <= skew_tolerance_s, f"{skew:.2f}s"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("clock skew", False, f"server time unavailable: {exc}"))
    for iid in sorted(adapter.symbols):
        out.append(
            Check(
                f"market {adapter.symbols[iid]}",
                adapter.min_amount(iid) > 0,
                f"min amount {adapter.min_amount(iid)}, step {adapter.lot_step(iid)}",
            )
        )
    try:
        bal = adapter.get_balances()
        out.append(
            Check(
                "balance query (Query Funds permission)",
                True,
                f"USD {bal.get('USD')}; holdings "
                f"{ {k: str(v) for k, v in bal.items() if k != 'USD'} or 'none' }",
            )
        )
        held = [k for k, v in bal.items() if k != "USD" and v > adapter.lot_step(k)]
        out.append(
            Check(
                "dedicated account (no BTC/ETH at first start)",
                not held,
                "ok" if not held else f"holds {held}; use an empty (sub-)account",
            )
        )
    except Exception as exc:  # noqa: BLE001
        ok, msg = _classify(exc, False)
        out.append(Check("balance query (Query Funds permission)", ok, msg))
        return out
    for iid in sorted(adapter.symbols):
        amount = adapter.min_amount(iid)
        price = _last_price(data, iid, now)
        try:
            adapter.validate_only(iid, "buy", amount)
            out.append(Check(f"validate market buy {iid}", True, f"{amount} accepted (not placed)"))
        except Exception as exc:  # noqa: BLE001
            ok, msg = _classify(exc, True)
            out.append(Check(f"validate market buy {iid}", ok, msg))
        if price is not None:
            try:
                adapter.validate_only(iid, "sell", amount, stop_price=price * Decimal("0.9"))
                out.append(Check(f"validate stop-loss {iid}", True, "accepted (not placed)"))
            except Exception as exc:  # noqa: BLE001
                ok, msg = _classify(exc, True)
                out.append(Check(f"validate stop-loss {iid}", ok, msg))
    out.append(
        Check(
            "withdrawal permission",
            True,
            "cannot be checked through the API: confirm on Kraken that the key has "
            "NO 'Withdraw Funds' permission",
        )
    )
    return out


def _last_price(data: KrakenMarketData, iid: str, now: datetime) -> Any:
    """
    Latest complete 4h close, for the stop-shape check.

    Args:
        data (KrakenMarketData): Market data.
        iid (str): Instrument.
        now (datetime): Time.

    Returns:
        Any: Decimal price or None.
    """
    try:
        bars = data.candles(iid, "4h", now)
    except Exception:  # noqa: BLE001
        return None
    return bars[-1].close if bars else None
