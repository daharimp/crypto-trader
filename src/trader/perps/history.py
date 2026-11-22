"""Read-only history of the forward paper perps session, rebuilt from its event log (ADR-031).

The session appends one JSON line per account event. This module pairs each ``OPENED`` with
the ``CLOSED`` or ``LIQUIDATED`` that ended it, and lists the equity the account recorded at
its start and at each day change. It never writes, and it never needs the perps parameters.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Reason: the dashboard reads this file on every refresh; a few events are written per hour,
# so 4 MB is years of history, and the cap keeps one request from reading without bound.
MAX_BYTES = 4_000_000
_OPEN_KEYS = ("size_usd", "collateral_usd", "entry", "leverage", "liquidation_price")


def _events(events_path: Path) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []
    with events_path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - MAX_BYTES))
        raw = f.read().decode("utf-8", errors="replace")
    lines = raw.splitlines()
    if size > MAX_BYTES:
        lines = lines[1:]  # the first line may be cut in half
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written last line must not hide the rest
        if isinstance(e, dict) and "event" in e and "at_utc" in e:
            out.append(e)
    return out


def _net(pnl: Any, fees: Any) -> str | None:
    try:
        return str(Decimal(str(pnl)) - Decimal(str(fees)))
    except (InvalidOperation, TypeError):
        return None


def _plus(net: str | None, partial: Decimal) -> str | None:
    return None if net is None else str(Decimal(net) + partial) if partial else net


def read_history(events_path: Path) -> dict[str, Any]:
    """
    Closed trades, recorded equity points and open-position details from the event log.

    Args:
        events_path (Path): The session's ``perps-paper-events.jsonl``.

    Returns:
        dict[str, Any]: ``trades`` (newest first; ``pnl_usd`` is after closing and borrow
        fees and includes any take-profits taken along the way (ADR-043), and a liquidation
        loses the whole collateral), ``equity`` (oldest first, one
        point at the start and one per day change) and ``open`` (per market: the leverage
        and liquidation price recorded when the position opened).
    """
    opened: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    for e in _events(events_path):
        kind, market = e["event"], e.get("market")
        if kind == "ACCOUNT_STARTED":
            equity.append({"at_utc": e["at_utc"], "equity_usd": e.get("cash_usd")})
        elif kind == "DAY_ROLLED":
            equity.append({"at_utc": e["at_utc"], "equity_usd": e.get("equity_usd")})
        elif kind == "OPENED" and market:
            opened[market] = {
                "market": market,
                "side": e.get("side"),
                "opened_at": e["at_utc"],
                **{k: e.get(k) for k in _OPEN_KEYS},
            }
        elif kind == "TAKE_PROFIT" and market and market in opened:
            # ADR-043: a partial close; its net is added to the trade when the rest closes.
            o = opened[market]
            part = _net(e.get("pnl_usd"), e.get("fees_usd"))
            o["take_profits"] = o.get("take_profits", 0) + 1
            o["_partial"] = str(Decimal(o.get("_partial", "0")) + Decimal(part or "0"))
        elif kind in ("CLOSED", "LIQUIDATED") and market:
            o = opened.pop(market, {"market": market, "side": e.get("side")})
            partial = Decimal(o.pop("_partial", "0"))
            liquidated = kind == "LIQUIDATED"
            lost = e.get("collateral_lost_usd")
            trades.append(
                {
                    **o,
                    "closed_at": e["at_utc"],
                    "exit": e.get("mark") if liquidated else e.get("exit"),
                    "pnl_usd": _plus(
                        (None if lost is None else str(-Decimal(str(lost))))
                        if liquidated
                        else _net(e.get("pnl_usd"), e.get("fees_usd")),
                        partial,
                    ),
                    "reason": "liquidated" if liquidated else e.get("reason"),
                    "liquidated": liquidated,
                }
            )
    trades.reverse()
    return {"trades": trades, "equity": equity, "open": opened}


def with_history(status: dict[str, Any] | None, events_path: Path) -> dict[str, Any] | None:
    """
    Add the history to a session summary for the dashboard.

    Args:
        status (dict[str, Any] | None): ``trader.perps.session.read_status`` output.
        events_path (Path): The session's event log.

    Returns:
        dict[str, Any] | None: The summary with ``trades`` and ``equity``, and each open
        position extended with ``leverage``, ``liquidation_price`` and ``opened_at`` when the
        log has its opening; None when no session has run.
    """
    if status is None:
        return None
    h = read_history(events_path)
    positions = []
    for p in status.get("positions", []):
        o = h["open"].get(p["market"])
        # Reason: only attach the recorded opening if it is this position, not an older one
        # on the same market whose close line was lost.
        same = o is not None and o.get("entry") == p.get("entry_price")
        extra = {k: o[k] for k in ("leverage", "liquidation_price", "opened_at")} if same else {}
        positions.append({**p, **extra})
    return {**status, "positions": positions, "trades": h["trades"], "equity": h["equity"]}
