"""T-40: journal-before-act: a journal failure means nothing is submitted."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import small_run
from trader.domain.enums import EventType
from trader.execution.adapters.simulated import SimulatedExecutionAdapter
from trader.journal.store import JournalStore, JournalWriteError, read_events


class FailingJournal(JournalStore):
    """Raises on the first ORDER_INTENT_CREATED."""

    def append(self, event_type: EventType, *a: Any, **kw: Any):  # type: ignore[override]
        if event_type == EventType.ORDER_INTENT_CREATED:
            raise JournalWriteError("disk full (simulated)")
        return super().append(event_type, *a, **kw)


def test_t40_no_submit_after_journal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-40: adapter.submit_order not called; RUN_FAILED; kill switch engaged; exit 1."""
    calls: list[Any] = []
    monkeypatch.setattr(
        SimulatedExecutionAdapter, "submit_order", lambda self, intent: calls.append(intent)
    )
    r = small_run(journal_factory=FailingJournal)
    assert r.exit_code == 1 and calls == []
    ev = read_events(r.run_id)
    failed = [e["payload"] for e in ev if e["event_type"] == "RUN_FAILED"]
    assert failed and failed[0]["kill_switch_engaged"] is True
    assert "journal write failed" in failed[0]["message"]
    assert not [e for e in ev if e["event_type"] in ("ORDER_SUBMITTED", "ORDER_FILLED")]
