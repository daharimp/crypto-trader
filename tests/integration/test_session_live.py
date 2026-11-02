"""Live sessions against a fake Kraken (ADR-023). Nothing here touches a real exchange."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tests.session_support import START, activate, configs, make_runner, run_ticks
from trader.common.opstore import OperationalStore
from trader.domain.enums import Environment
from trader.execution.adapters.kraken_live import _ALLOWED_PARAMS
from trader.journal.store import read_events
from trader.journal.verify import verify
from trader.profiles.compiler import compile_bundle, exit_code
from trader.session.config import SessionError

L, P = Environment.LIVE, Environment.PAPER


def _live_ready(tmp: Path, monkeypatch: pytest.MonkeyPatch, **auth: object):  # type: ignore[no-untyped-def]
    root = configs(tmp, **auth)  # type: ignore[arg-type]
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(root))
    store = OperationalStore()
    activate(root, P, store)
    store.record_paper_cycle("balanced-paper", 4, START)
    activate(root, L, store)
    return root, store


def _until_position(runner, clock, n: int = 40) -> None:  # type: ignore[no-untyped-def]
    for _ in range(n):
        runner.tick()
        clock.set(clock.now() + timedelta(hours=4))
        if runner.state.ledger.positions:
            return
    raise AssertionError("no position opened")


def test_live_entry_places_capped_order_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entry: market buy within the cap, fees in USD, then a resting stop-loss at Kraken."""
    root, store = _live_ready(tmp_path, monkeypatch)
    runner, fake, clock = make_runner(root, L, store)
    runner.start()
    assert runner.state.ledger.cash == Decimal(500)  # min(USD 1000, cap 500)
    _until_position(runner, clock)
    creates = [c for c in fake.calls if c[0] == "create_order"]
    assert all(set(c[2]) <= _ALLOWED_PARAMS for c in creates)
    assert all(c[2]["oflags"] == "fciq" and isinstance(c[2]["userref"], int) for c in creates)
    buy = next(c for c in creates if c[1][2] == "buy")
    assert Decimal(str(buy[1][3])) * 130 <= Decimal(500)
    stops = [o for o in fake.orders.values() if "stop" in o and o["status"] == "open"]
    assert len(stops) == 1 and stops[0]["side"] == "sell"
    pos = runner.state.ledger.positions["BTC-USD"]
    assert Decimal(str(fake.balances["BTC"])) == pos.quantity
    assert not runner.kill.is_engaged()


def test_live_stop_out_and_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gap down triggers the Kraken stop; the ledger books it; every order traces (D-36)."""
    root, store = _live_ready(tmp_path, monkeypatch)
    runner, fake, clock = make_runner(root, L, store)
    runner.start()
    run_ticks(runner, clock, 45)
    st = runner.state
    assert st.ledger.trades and not st.ledger.positions
    assert fake.balances.get("BTC", Decimal(0)) == 0
    types = [e["event_type"] for e in read_events(st.journal.run_id)]
    assert "STOP_TRIGGERED" in types and "RECONCILIATION_FAILED" not in types
    res = verify(st.journal.run_id)
    assert res.ok, res.errors
    assert not runner.kill.is_engaged()


def test_live_reconciliation_mismatch_halts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone else changes the account -> mismatch -> persisted kill switch; no new entries."""
    root, store = _live_ready(tmp_path, monkeypatch)
    runner, fake, clock = make_runner(root, L, store)
    runner.start()
    _until_position(runner, clock)
    fake.balances["BTC"] += Decimal("0.5")
    run_ticks(runner, clock, 2)
    assert runner.kill.is_engaged()
    assert runner.kill.state().trigger == "reconciliation_mismatch"  # type: ignore[union-attr]


def test_live_owner_flatten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flatten cancels the Kraken stop and sells immediately, even with the kill switch on."""
    root, store = _live_ready(tmp_path, monkeypatch)
    runner, fake, clock = make_runner(root, L, store)
    runner.start()
    _until_position(runner, clock)
    runner.kill.engage("owner halt", clock.now())
    store.request("flatten", "get out", clock.now())
    runner.tick()
    assert not runner.state.ledger.positions
    assert fake.balances.get("BTC", Decimal(0)) == 0
    assert any(c[0] == "cancel_order" for c in fake.calls)


def test_live_submit_timeout_recovers_by_userref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout after Kraken accepted the order is recovered via userref (no duplicate)."""
    root, store = _live_ready(tmp_path, monkeypatch)
    runner, fake, clock = make_runner(root, L, store)
    runner.start()
    fake.fail_next_create = True
    _until_position(runner, clock)
    buys = [c for c in fake.calls if c[0] == "create_order" and c[1][2] == "buy"]
    assert len(buys) == 1
    assert Decimal(str(fake.balances["BTC"])) == runner.state.ledger.positions["BTC-USD"].quantity


@pytest.mark.parametrize(
    ("auth", "code", "text"),
    [
        ({"cap": None}, 3, "UD-22"),
        ({"cycles": None}, 3, "UD-22"),
        ({"ack": False}, 2, "LIVE_NOT_ACKNOWLEDGED"),
    ],
)
def test_live_gates(
    auth: dict[str, object], code: int, text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure: unresolved cap or paper requirement (exit 3); no acknowledgement (exit 2)."""
    root = configs(tmp_path, **auth)  # type: ignore[arg-type]
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(root))
    store = OperationalStore()
    store.record_paper_cycle("balanced-paper", 4, START)  # isolate the gate under test
    c = compile_bundle(
        root / "profiles" / "balanced-paper.yaml", L, None, root, None, store, assume_activated=True
    ).compiled
    assert exit_code(c) == code
    assert text in " ".join(c.errors) + " ".join(b.ref for b in c.blockers)


def test_live_needs_paper_track_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure: fewer completed paper cycles than the owner requires."""
    root = configs(tmp_path, cycles=3)
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(root))
    store = OperationalStore()
    store.record_paper_cycle("balanced-paper", 4, START)
    c = compile_bundle(
        root / "profiles" / "balanced-paper.yaml", L, None, root, None, store, assume_activated=True
    ).compiled
    assert any("paper track record 1 cycles < required 3" in e for e in c.errors)


def test_live_refuses_account_with_holdings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure: the account already holds BTC at first start."""
    root, store = _live_ready(tmp_path, monkeypatch)
    runner, fake, _ = make_runner(root, L, store)
    fake.balances["BTC"] = Decimal("0.1")
    with pytest.raises(SessionError, match="already holds"):
        runner.start()


def test_live_without_activation_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure: an approved authorization alone is not enough; live needs activation."""
    root = configs(tmp_path)
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(root))
    store = OperationalStore()
    store.record_paper_cycle("balanced-paper", 4, START)
    runner, _, _ = make_runner(root, L, store)
    with pytest.raises(SessionError, match="activation"):
        runner.start()


def test_live_config_change_mid_session_halts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FM-15: editing the risk config while running engages the kill switch."""
    root, store = _live_ready(tmp_path, monkeypatch)
    runner, _, clock = make_runner(root, L, store)
    runner.start()
    runner.tick()
    rp = root / "risk" / "balanced.yaml"
    rp.write_text(
        rp.read_text().replace(
            "value: 3, status: approved, ref: UD-17", "value: 4, status: approved, ref: UD-17", 1
        )
    )
    clock.set(clock.now() + timedelta(hours=4))
    runner.tick()
    assert runner.kill.is_engaged()
    assert runner.kill.state().trigger == "risk_config_invalid_mid_session"  # type: ignore[union-attr]


def test_live_clock_skew_halts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Clock skew above the approved 5 s engages the kill switch."""
    root, store = _live_ready(tmp_path, monkeypatch)
    runner, fake, _ = make_runner(root, L, store)
    runner.start()
    fake.clock_offset_s = 30
    runner.tick()
    assert runner.kill.state().trigger == "clock_skew_exceeded"  # type: ignore[union-attr]
