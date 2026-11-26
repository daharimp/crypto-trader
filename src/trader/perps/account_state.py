"""What a paper perps account saves between cycles, and how it is read back (ADR-031).

Kept apart from the session so that both stay small. Every key added after the first
version is read with a default, so a state file written by older code still loads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .math import PerpSide
from .params import PerpsParams
from .position import PerpPosition
from .simulator import PaperPerpsAccount


def iso(t: datetime) -> str:
    """``t`` as an ISO string in UTC."""
    return t.astimezone(UTC).isoformat()


def dump_account(acct: PaperPerpsAccount) -> dict[str, Any]:
    """The account as plain JSON-ready values."""
    return {
        "cash_usd": str(acct.cash_usd),
        "day_start_equity_usd": str(acct.day_start_equity_usd),
        "day": acct.day,
        "realized_pnl_usd": str(acct.realized_pnl_usd),
        "fees_paid_usd": str(acct.fees_paid_usd),
        "stopped_today": sorted(acct.stopped_today),
        "day_halted": acct.day_halted,
        "cooldown_until": {m: iso(t) for m, t in sorted(acct.cooldown_until.items())},
        "positions": {
            m: {
                "side": p.side.value,
                "size_usd": str(p.size_usd),
                "collateral_usd": str(p.collateral_usd),
                "entry_price": str(p.entry_price),
                "opened_at": iso(p.opened_at),
                "borrow_fees_usd": str(p.borrow_fees_usd),
                "last_accrual": iso(p.last_accrual) if p.last_accrual else None,
                "initial_stop": None if p.initial_stop is None else str(p.initial_stop),
                "tps_hit": p.tps_hit,
                "moved_stop": None if p.moved_stop is None else str(p.moved_stop),
                "realized_usd": str(p.realized_usd),
            }
            for m, p in acct.positions.items()
        },
    }


def load_account(params: PerpsParams, d: dict[str, Any]) -> PaperPerpsAccount:
    """An account rebuilt from ``dump_account`` output, under ``params``."""
    acct = PaperPerpsAccount(
        params, Decimal(d["cash_usd"]), Decimal(d["day_start_equity_usd"]), d["day"]
    )
    acct.realized_pnl_usd = Decimal(d["realized_pnl_usd"])
    acct.fees_paid_usd = Decimal(d["fees_paid_usd"])
    # Reason: state files written before ADR-038 have neither key.
    acct.stopped_today = set(d.get("stopped_today", []))
    acct.day_halted = bool(d.get("day_halted", False))
    if params.cooldown_after_loss_hours is not None:
        # Reason: waits saved while the setting was on end with it; state written before
        # ADR-053 has neither this key nor a position's ``realized_usd``.
        waits = d.get("cooldown_until", {}).items()
        acct.cooldown_until = {m: datetime.fromisoformat(t) for m, t in waits}
    for m, p in d["positions"].items():
        acct.positions[m] = PerpPosition(
            m,
            PerpSide(p["side"]),
            Decimal(p["size_usd"]),
            Decimal(p["collateral_usd"]),
            Decimal(p["entry_price"]),
            datetime.fromisoformat(p["opened_at"]),
            Decimal(p["borrow_fees_usd"]),
            datetime.fromisoformat(p["last_accrual"]) if p["last_accrual"] else None,
            # Reason: state written before ADR-045 has no ladder keys.
            None if p.get("initial_stop") is None else Decimal(p["initial_stop"]),
            int(p.get("tps_hit", 0)),
            None if p.get("moved_stop") is None else Decimal(p["moved_stop"]),
            Decimal(p.get("realized_usd", "0")),
        )
    return acct
