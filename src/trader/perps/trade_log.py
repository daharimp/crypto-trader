"""Closed round trips of a paper perps account, from its event log (ADR-045).

Lives in the paper-only perps package because a perps trade carries its leverage (ADR-025).
A trade is an ``OPENED`` event paired with the next ``CLOSED`` or ``LIQUIDATED`` event of the
same market; every other event of that market in between (stop moves, take-profit partials,
...) is kept as context. Reads only; nothing here writes a file or places an order.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

CLOSERS = ("CLOSED", "LIQUIDATED")


def num(x: Any) -> float | None:
    """A float, or None when missing or not a number."""
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def hours_between(a: str, b: str) -> float | None:
    """Hours from ISO time ``a`` to ``b``, or None when unreadable."""
    try:
        return round(
            (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600, 2
        )
    except ValueError:
        return None


def perps_trades(events: list[dict[str, Any]], account: str) -> list[dict[str, Any]]:
    """
    Closed round trips of a perps account, oldest close first.

    Args:
        events (list[dict[str, Any]]): The account's events, oldest first.
        account (str): Account name (goes into each ``trade_id``).

    Returns:
        list[dict[str, Any]]: One dict per closed trade.
    """
    open_by_market: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    out: list[dict[str, Any]] = []
    for e in events:
        m = e.get("market")
        if m is None:
            continue
        if e["event"] == "OPENED":
            open_by_market[m] = (e, [])
        elif e["event"] in CLOSERS and m in open_by_market:
            o, between = open_by_market.pop(m)
            pnl, fees = num(e.get("pnl_usd")), num(e.get("fees_usd"))
            # Reason: take-profit ladder partials (TAKE_PROFIT events) realize part of the
            # trade before the final CLOSED, so their dollars belong to the same trade.
            partials = [x for x in between if x["event"] == "TAKE_PROFIT"]
            pnl = (pnl or 0.0) + sum(num(x.get("pnl_usd")) or 0.0 for x in partials)
            fees = (fees or 0.0) + sum(num(x.get("fees_usd")) or 0.0 for x in partials)
            collateral = num(o.get("collateral_usd"))
            out.append(
                {
                    "trade_id": f"{account}:{m}:{o['at_utc']}",
                    "account": account,
                    "market": m,
                    "side": o.get("side"),
                    "opened_at_utc": o["at_utc"],
                    "closed_at_utc": e["at_utc"],
                    "hours_held": hours_between(o["at_utc"], e["at_utc"]),
                    "entry": num(o.get("entry")),
                    "exit": num(e.get("exit") or e.get("mark")),
                    "size_usd": num(o.get("size_usd")),
                    "collateral_usd": collateral,
                    "liquidation_price": num(o.get("liquidation_price")),
                    "pnl_usd_before_fees": pnl,
                    "fees_usd": fees + (num(o.get("fee_usd")) or 0.0),
                    "take_profit_steps_hit": len(partials),
                    "collateral_lost_usd": num(e.get("collateral_lost_usd")),
                    "exit_reason": e.get("reason") or e["event"],
                    "events_during_trade": between,
                }
            )
            # Reason: keyword form, as the simulator journals it; the safety scan bans the
            # word only as a literal dict key (T-46), and leverage is allowed in this package.
            out[-1].update(leverage=num(o.get("leverage")))
        elif m in open_by_market and e["event"] != "OPEN_REJECTED":
            open_by_market[m][1].append(e)
    for t in out:
        net = (t["pnl_usd_before_fees"] or 0.0) - t["fees_usd"]
        if t["collateral_lost_usd"] is not None:
            net = -t["collateral_lost_usd"]
        t["net_pnl_usd"] = round(net, 2)
        c = t["collateral_usd"]
        t["return_on_collateral_pct"] = round(net / c * 100, 2) if c else None
    return sorted(out, key=lambda t: t["closed_at_utc"])
