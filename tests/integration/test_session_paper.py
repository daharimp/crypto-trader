"""Forward paper sessions on (fake) live Kraken data (BL-027; T-50 to T-52)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tests.session_support import activate, configs, make_runner, run_ticks
from trader.common.opstore import OperationalStore
from trader.domain.enums import Environment
from trader.journal.store import read_events
from trader.journal.verify import verify
from trader.session.config import SessionError

P = Environment.PAPER


@pytest.fixture
def paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    root = configs(tmp_path)
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(root))
    store = OperationalStore()
    activate(root, P, store)
    return root, store


def test_paper_session_trades_and_stops(paper) -> None:  # type: ignore[no-untyped-def]
    """Expected: entry on the cross, protective stop, stop-out on the gap; journal verifies."""
    root, store = paper
    runner, _, clock = make_runner(root, P, store)
    runner.start()
    run_ticks(runner, clock, 45)
    st = runner.state
    assert st.counts["order_intents"] >= 2 and st.counts["fills"] >= 2
    ev = read_events(st.journal.run_id)
    types = [e["event_type"] for e in ev]
    assert "STOP_TRIGGERED" in types or st.ledger.trades
    assert verify(st.journal.run_id).ok
    assert store.paper_cycle_count("balanced-paper", 3) == 45
    assert not st.controls.kill_switch.engaged


def test_paper_restart_restores_state(paper) -> None:  # type: ignore[no-untyped-def]
    """Restart mid-position: ledger, stops, and IDs are restored; no duplicate cycles."""
    root, store = paper
    runner, fake, clock = make_runner(root, P, store)
    runner.start()
    # Run until a position is open.
    for _ in range(40):
        runner.tick()
        clock.set(clock.now() + timedelta(hours=4))
        if runner.state.ledger.positions:
            break
    assert runner.state.ledger.positions
    before = (
        runner.state.ledger.cash,
        dict(runner.state.ledger.positions),
        set(runner.state.stops),
        runner.meta["last_t1"],
    )
    runner.state.journal.close()
    again, _, _ = make_runner(root, P, store, fake=fake, clock=clock)
    again.start()
    assert (
        again.state.ledger.cash,
        again.state.ledger.positions.keys(),
        set(again.state.stops),
        again.meta["last_t1"],
    ) == (before[0], before[1].keys(), before[2], before[3])
    again.tick()  # same bar: nothing new to process
    assert again.meta["last_t1"] == before[3] or again.meta["last_t1"] > before[3]
    state_file = json.loads(again.path.read_text())
    assert state_file["meta"]["environment"] == "paper"


def test_paper_kill_switch_blocks_entries(paper) -> None:  # type: ignore[no-untyped-def]
    """The persisted kill switch (owner CLI) blocks every new entry in a running session."""
    root, store = paper
    runner, _, clock = make_runner(root, P, store)
    runner.start()
    runner.kill.engage("owner drill", clock.now())
    run_ticks(runner, clock, 45)
    assert runner.state.counts["order_intents"] == 0
    risk = [
        e["payload"]
        for e in read_events(runner.state.journal.run_id)
        if e["event_type"] == "RISK_EVALUATED"
    ]
    assert risk and all(r["reason_codes"] == ["KILL_SWITCH_ENGAGED"] for r in risk)


def test_paper_owner_flatten(paper) -> None:  # type: ignore[no-untyped-def]
    """Owner flatten sells through the risk engine even with the kill switch engaged."""
    root, store = paper
    runner, _, clock = make_runner(root, P, store)
    runner.start()
    for _ in range(40):
        runner.tick()
        clock.set(clock.now() + timedelta(hours=4))
        if runner.state.ledger.positions:
            break
    assert runner.state.ledger.positions
    runner.kill.engage("halt", clock.now())
    store.request("flatten", "owner wants out", clock.now())
    runner.tick()  # queues the exit (paper fills at the next bar open)
    clock.set(clock.now() + timedelta(hours=4))
    runner.tick()
    assert not runner.state.ledger.positions
    assert store.pending_request("flatten") is None
    assert verify(runner.state.journal.run_id).ok


def test_paper_requires_activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure: no activation record -> the session refuses to start (exit 2)."""
    root = configs(tmp_path)
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(root))
    runner, _, _ = make_runner(root, P, OperationalStore())
    with pytest.raises(SessionError) as exc:
        runner.start()
    assert exc.value.exit_code == 2 and "activation" in str(exc.value)


def test_paper_stale_data_escalates(paper) -> None:  # type: ignore[no-untyped-def]
    """Data stops arriving -> stale cycles -> kill switch after the approved 3 cycles."""
    root, store = paper
    runner, fake, clock = make_runner(root, P, store)
    runner.start()
    runner.tick()
    fake.candles = {
        s: [c for c in v if c.open_time_utc < clock.now()] for s, v in fake.candles.items()
    }  # feed freezes
    # The first bar after the freeze is still complete; the next three are stale.
    run_ticks(runner, clock, 6)
    assert runner.kill.is_engaged()
    assert runner.meta["stale_cycles"] >= 3
    assert runner.kill.state().trigger == "persistent_stale_data"  # type: ignore[union-attr]
