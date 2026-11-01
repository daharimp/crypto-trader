"""Journal verification: hash chain and D-36 traceability (§7.11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trader.common.clock import parse_utc
from trader.common.hashing import GENESIS_HASH

from .store import event_content, hash_content, read_events


@dataclass
class VerifyResult:
    """Outcome of ``verify``."""

    ok: bool
    n_events: int
    n_orders: int
    root_hash: str
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """
        One-line summary.

        Returns:
            str: ``OK <n> events, <m> orders traceable, root <hash>`` or the first error.
        """
        if self.ok:
            return (
                f"OK {self.n_events} events, {self.n_orders} orders traceable, "
                f"root {self.root_hash}"
            )
        return "JOURNAL_INTEGRITY_FAILED: " + "; ".join(self.errors[:5])


def verify(run_id: str, path: Path | None = None) -> VerifyResult:
    """
    Recompute the chain and check every ORDER_INTENT_CREATED is traceable (D-36).

    Args:
        run_id (str): Run ID.
        path (Path | None): Journal path.

    Returns:
        VerifyResult: Result (``ok`` False on any mismatch).
    """
    events = read_events(run_id, path)
    errors: list[str] = []
    prev = GENESIS_HASH
    for i, e in enumerate(events, start=1):
        if e["seq"] != i:
            errors.append(f"seq gap at {i}")
        if e["prev_event_hash"] != prev:
            errors.append(f"seq {e['seq']}: prev hash mismatch")
        if hash_content(prev, event_content(e)) != e["event_hash"]:
            errors.append(f"seq {e['seq']}: event hash mismatch")
        prev = e["event_hash"]
    if not events:
        errors.append("no events for run")
    errors.extend(_traceability(events))
    orders = [e for e in events if e["event_type"] == "ORDER_INTENT_CREATED"]
    return VerifyResult(not errors, len(events), len(orders), prev, errors)


def _traceability(events: list[dict[str, Any]]) -> list[str]:
    """
    Check D-36 for every order intent.

    Args:
        events (list[dict[str, Any]]): Events.

    Returns:
        list[str]: Problems.
    """
    errs: list[str] = []
    compiled = [e for e in events if e["event_type"] == "PROFILE_COMPILED"]
    run_hash = compiled[0]["payload"].get("config_hash") if compiled else None
    signals = {
        e["payload"]["signal_id"]: e["payload"]
        for e in events
        if e["event_type"] == "SIGNAL_GENERATED"
    }
    risks = {
        e["payload"]["risk_decision_id"]: e["payload"]
        for e in events
        if e["event_type"] == "RISK_EVALUATED"
    }
    snaps: set[tuple[str, str]] = set()
    for e in events:
        if e["event_type"] == "FEATURES_COMPUTED" and e["payload"].get("snapshot"):
            s = e["payload"]["snapshot"]
            if s.get("latest_bar"):
                snaps.add((s["instrument_id"], s["latest_bar"]["close_time_utc"]))
    for e in events:
        if e["event_type"] != "ORDER_INTENT_CREATED":
            continue
        o = e["payload"]
        oid = o["order_intent_id"]
        for sid in o["signal_ids"]:
            sig = signals.get(sid)
            if sig is None or not sig.get("strategy_id") or not sig.get("strategy_version"):
                errs.append(f"{oid}: signal {sid} missing or unversioned")
        if not o["strategy_versions"]:
            errs.append(f"{oid}: no strategy versions")
        rd = risks.get(o["risk_decision_id"])
        if rd is None or rd["status"] not in ("approved", "modified"):
            errs.append(f"{oid}: approved risk decision missing")
        if run_hash is None or o["config_hash"] != run_hash:
            errs.append(f"{oid}: config_hash does not match PROFILE_COMPILED")
        if parse_utc(o["market_data_timestamp_utc"]) > parse_utc(o["decision_time_utc"]):
            errs.append(f"{oid}: market data after decision time")
        if o["purpose"] != "protective_stop" and (
            (o["instrument_id"], o["market_data_timestamp_utc"]) not in snaps
        ):
            errs.append(f"{oid}: no journaled snapshot at market_data_timestamp_utc")
    return errs
