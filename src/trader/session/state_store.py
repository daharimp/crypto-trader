"""Persist forward-session state between cycles and across restarts (BL-027)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trader.common.canonical import to_canonical_obj
from trader.common.clock import parse_utc
from trader.common.paths import data_root
from trader.domain.enums import Environment
from trader.domain.orders import OrderIntent
from trader.domain.risk import RiskDecision
from trader.pipeline.state import RunState
from trader.portfolio.ledger import ClosedTrade, _Position

STATE_VERSION = 1


def state_path(environment: Environment, profile_id: str) -> Path:
    """
    Session state file for an environment and profile (paper and live never share one).

    Args:
        environment (Environment): ``paper`` or ``live``.
        profile_id (str): Profile ID.

    Returns:
        Path: ``data/state/session-<environment>-<profile_id>.json``.
    """
    return data_root() / "state" / f"session-{environment.value}-{profile_id}.json"


def _dt(v: str | None) -> datetime | None:
    """
    Parse an optional UTC timestamp.

    Args:
        v (str | None): Text.

    Returns:
        datetime | None: Value.
    """
    return parse_utc(v) if v else None


def save_state(path: Path, state: RunState, meta: dict[str, Any]) -> None:
    """
    Atomically write the session state (write to a temp file, then rename).

    Args:
        path (Path): State file.
        state (RunState): Run state.
        meta (dict[str, Any]): Session metadata (environment, last cycle, stale count, ...).
    """
    led, ctl = state.ledger, state.controls
    keep = {i.risk_decision_id for i in [*state.pending.values(), *state.stops.values()]}
    data = {
        "state_version": STATE_VERSION,
        "meta": meta,
        "ledger": {
            "cash": led.cash,
            "positions": {k: asdict(p) for k, p in led.positions.items()},
            "realized_pnl": led.realized_pnl,
            "trades": [asdict(t) for t in led.trades],
            "fees_usd": led.fees_usd,
            "slippage_usd": led.slippage_usd,
        },
        "loss": {
            "equity": state.loss.equity,
            "hwm": state.loss.hwm,
            "day_start": state.loss.day_start,
        },
        "controls": {
            "breaker_open": ctl.breaker.open,
            "breaker_opened_at": ctl.breaker.opened_at,
            "lockout_until": ctl.lockout.until,
            "cooldown_losses": ctl.cooldowns.losses,
            "cooldown_until": ctl.cooldowns.until,
            "consecutive_errors": ctl.consecutive_errors,
            "kill_switch_engaged": ctl.kill_switch.engaged,
            "kill_switch_reason": ctl.kill_switch.reason,
        },
        "pending": {k: v.model_dump(mode="json") for k, v in state.pending.items()},
        "stops": {k: v.model_dump(mode="json") for k, v in state.stops.items()},
        "decisions": {
            k: v.model_dump(mode="json") for k, v in state.decisions.items() if k in keep
        },
        "used_keys": sorted(state.used_keys),
        "filled_entries": sorted(state.filled_entries),
        "counts": dict(state.counts),
        "rejections": dict(state.rejections),
        "ids": dict(state.ids._counters),
        "adapter": state.adapter.export_state(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(to_canonical_obj(data), indent=1, sort_keys=True))
    os.replace(tmp, path)


def load_state(path: Path, state: RunState) -> dict[str, Any] | None:
    """
    Restore state saved by :func:`save_state` into a freshly built RunState.

    Args:
        path (Path): State file.
        state (RunState): Newly constructed run state (updated in place).

    Returns:
        dict[str, Any] | None: Saved metadata, or None if no state file exists.

    Raises:
        ValueError: If the file has an unknown state version.
    """
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get("state_version") != STATE_VERSION:
        raise ValueError(f"unsupported session state version in {path}")
    D = Decimal
    lg = data["ledger"]
    led = state.ledger
    led.cash = D(lg["cash"])
    led.positions = {
        k: _Position(
            D(p["quantity"]),
            D(p["avg_entry_price"]),
            D(p["cost_basis_usd"]),
            parse_utc(p["opened_at"]),
            p["tier"],
            list(p["owners"]),
            D(p["stop_price"]) if p["stop_price"] is not None else None,
            D(p["mark"]),
        )
        for k, p in lg["positions"].items()
    }
    led.realized_pnl = {k: D(v) for k, v in lg["realized_pnl"].items()}
    led.trades = [
        ClosedTrade(
            t["instrument_id"],
            list(t["strategy_ids"]),
            parse_utc(t["opened_at"]),
            parse_utc(t["closed_at"]),
            D(t["quantity"]),
            D(t["entry_price"]),
            D(t["exit_price"]),
            D(t["pnl_usd"]),
        )
        for t in lg["trades"]
    ]
    led.fees_usd, led.slippage_usd = D(lg["fees_usd"]), D(lg["slippage_usd"])
    ls = data["loss"]
    state.loss.equity, state.loss.hwm, state.loss.day_start = (
        D(ls["equity"]),
        D(ls["hwm"]),
        D(ls["day_start"]),
    )
    c, ctl = data["controls"], state.controls
    ctl.breaker.open, ctl.breaker.opened_at = c["breaker_open"], _dt(c["breaker_opened_at"])
    ctl.lockout.until = _dt(c["lockout_until"])
    ctl.cooldowns.losses = {k: int(v) for k, v in c["cooldown_losses"].items()}
    ctl.cooldowns.until = {k: parse_utc(v) for k, v in c["cooldown_until"].items()}
    ctl.consecutive_errors = int(c["consecutive_errors"])
    if c["kill_switch_engaged"]:
        ctl.kill_switch.engage(c["kill_switch_reason"] or "restored", "restored_state")
    state.pending = {k: OrderIntent.model_validate(v) for k, v in data["pending"].items()}
    state.stops = {k: OrderIntent.model_validate(v) for k, v in data["stops"].items()}
    state.decisions.update(
        {k: RiskDecision.model_validate(v) for k, v in data["decisions"].items()}
    )
    state.used_keys = set(data["used_keys"])
    state.filled_entries = set(data["filled_entries"])
    state.counts.update(data["counts"])
    state.rejections.update(data["rejections"])
    state.ids._counters.update({k: int(v) for k, v in data["ids"].items()})
    state.adapter.load_state(data["adapter"])
    meta: dict[str, Any] = data["meta"]
    return meta
