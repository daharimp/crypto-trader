"""T-36: portfolio accounting and reconciliation; a mismatch engages the kill switch."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.conftest import small_run
from trader.execution.adapters.simulated import SimulatedExecutionAdapter
from trader.journal.store import read_events
from trader.journal.verify import verify


def test_clean_run_reconciles_every_fill() -> None:
    """Expected: no RECONCILIATION_FAILED in a clean run; journal verifies."""
    r = small_run()
    assert r.exit_code == 0
    types = [e["event_type"] for e in read_events(r.run_id)]
    assert "ORDER_FILLED" in types and "RECONCILIATION_FAILED" not in types
    assert verify(r.run_id).ok


def test_t36_mismatch_engages_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-36: injected adapter balance drift -> RECONCILIATION_FAILED, KILL_SWITCH_ENGAGED,
    and every later entry is rejected with KILL_SWITCH_ENGAGED."""
    original = SimulatedExecutionAdapter._fill
    state = {"done": False}

    def drifting(self, intent, prev, price, bar):  # type: ignore[no-untyped-def]
        rep = original(self, intent, prev, price, bar)
        if not state["done"] and rep.status == "filled":
            self.cash += Decimal("0.01")  # simulated venue drift
            state["done"] = True
        return rep

    monkeypatch.setattr(SimulatedExecutionAdapter, "_fill", drifting)
    r = small_run()
    assert r.exit_code == 0
    ev = read_events(r.run_id)
    types = [e["event_type"] for e in ev]
    i_rec = types.index("RECONCILIATION_FAILED")
    assert types[i_rec + 1] == "KILL_SWITCH_ENGAGED"
    later = [e["payload"] for e in ev[i_rec:] if e["event_type"] == "RISK_EVALUATED"]
    assert later and all(p["reason_codes"] == ["KILL_SWITCH_ENGAGED"] for p in later)
    assert not [
        e
        for e in ev[i_rec:]
        if e["event_type"] == "ORDER_INTENT_CREATED" and e["payload"]["purpose"] == "entry"
    ]
