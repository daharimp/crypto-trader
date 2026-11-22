"""Closed trades and equity of every paper account, read from saved files (ADR-045).

Accounts:

- ``main``, ``degen``, ``spot-perps``: paper perps accounts. A trade is an ``OPENED`` event
  paired with the next ``CLOSED`` or ``LIQUIDATED`` event of the same market; every other
  event of that market in between (stop moves, take-profit partials, ...) is kept as context.
- ``spot``: the paper spot session(s), ``data/state/session-paper-*.json``. Trades come from
  the ledger's closed round trips, which do not record why they closed.

Every number comes from code. Nothing here writes a file or places an order.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trader.perps.review_facts import ACCOUNTS as PERPS_ACCOUNTS
from trader.perps.review_facts import account_files, read_events
from trader.perps.session import read_status
from trader.perps.trade_log import hours_between as _hours
from trader.perps.trade_log import num as _f
from trader.perps.trade_log import perps_trades

SPOT = "spot"
ALL_ACCOUNTS = (*PERPS_ACCOUNTS, SPOT)


def spot_files(data_root: Path) -> list[Path]:
    """Paper spot session state files (one per profile)."""
    folder = data_root / "state"
    return sorted(folder.glob("session-paper-*.json")) if folder.exists() else []


def _read(path: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def spot_trades(data_root: Path) -> list[dict[str, Any]]:
    """
    Closed round trips of the paper spot session(s), oldest close first.

    Args:
        data_root (Path): Data directory.

    Returns:
        list[dict[str, Any]]: One dict per closed trade.
    """
    out: list[dict[str, Any]] = []
    for f in spot_files(data_root):
        d = _read(f)
        if d is None:
            continue
        for t in (d.get("ledger") or {}).get("trades", []):
            entry, exit_, qty = (
                _f(t.get("entry_price")),
                _f(t.get("exit_price")),
                _f(t.get("quantity")),
            )
            o, c = str(t.get("opened_at")), str(t.get("closed_at"))
            iid = str(t.get("instrument_id"))
            cost = entry * qty if entry and qty else None
            pnl = _f(t.get("pnl_usd"))
            out.append(
                {
                    "trade_id": f"{SPOT}:{iid}:{o}:{c}",
                    "account": SPOT,
                    "session": f.stem,
                    "market": iid.split("-")[0],
                    "side": "long",
                    "opened_at_utc": o,
                    "closed_at_utc": c,
                    "hours_held": _hours(o, c),
                    "entry": entry,
                    "exit": exit_,
                    "quantity": qty,
                    "size_usd": round(cost, 2) if cost else None,
                    "net_pnl_usd": pnl,
                    "return_on_cost_pct": round(pnl / cost * 100, 2)
                    if pnl is not None and cost
                    else None,
                    "exit_reason": "not recorded by the spot ledger (stop or trend exit)",
                    "strategies": t.get("strategy_ids"),
                }
            )
    return sorted(out, key=lambda t: t["closed_at_utc"])


def closed_trades(data_root: Path, account: str) -> list[dict[str, Any]]:
    """
    Closed trades of any account, oldest close first.

    Args:
        data_root (Path): Data directory.
        account (str): A name from ``ALL_ACCOUNTS``.

    Returns:
        list[dict[str, Any]]: Trades.

    Raises:
        ValueError: If the account is unknown.
    """
    if account == SPOT:
        return spot_trades(data_root)
    return perps_trades(read_events(account_files(data_root, account)[1]), account)


def equity_snapshot(data_root: Path, account: str) -> dict[str, Any] | None:
    """
    Current equity, its peak and the drawdown from that peak; None when never run.

    Args:
        data_root (Path): Data directory.
        account (str): A name from ``ALL_ACCOUNTS``.

    Returns:
        dict[str, Any] | None: ``equity_usd``, ``peak_usd``, ``start_usd``, ``drawdown_pct``,
        ``max_drawdown_pct`` (perps only), ``open_positions``.
    """
    if account == SPOT:
        eq = peak = start = 0.0
        n = 0
        found = False
        for f in spot_files(data_root):
            d = _read(f)
            if d is None:
                continue
            found = True
            led = d.get("ledger") or {}
            e = _f((d.get("meta") or {}).get("equity_usd")) or _f(led.get("cash")) or 0.0
            eq += e
            peak += max(_f((d.get("loss") or {}).get("hwm")) or e, e)
            start += _f((d.get("loss") or {}).get("day_start")) or e
            n += len(led.get("positions") or {})
        if not found:
            return None
        snap: dict[str, Any] = {"equity_usd": eq, "peak_usd": peak, "day_start_usd": start}
        snap["open_positions"] = n
    else:
        state, _ = account_files(data_root, account)
        try:
            st = read_status(state)
        except (OSError, ValueError, KeyError):
            return None
        if st is None:
            return None
        raw = _read(state) or {}
        eq = _f(st["equity_usd"]) or 0.0
        snap = {
            "equity_usd": eq,
            "peak_usd": max(_f((raw.get("meta") or {}).get("peak_equity_usd")) or eq, eq),
            "start_usd": _f(st["start_equity_usd"]),
            "max_drawdown_pct": _f(st["max_drawdown_pct"]),
            "open_positions": len(st["positions"]),
        }
    p = snap["peak_usd"]
    snap["drawdown_pct"] = round((p - snap["equity_usd"]) / p * 100, 2) if p > 0 else 0.0
    return snap
