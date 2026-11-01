"""T-37: the journal rejects UPDATE and DELETE."""

from __future__ import annotations

import sqlite3

import pytest

from tests.helpers import T0
from trader.domain.enums import EventType
from trader.journal.store import JournalStore, read_events


def test_t37_update_and_delete_rejected() -> None:
    """T-37: both raise (append-only triggers)."""
    j = JournalStore("run-x")
    j.append(EventType.RUN_STARTED, T0, {"a": 1}, payload_type="X")
    con = sqlite3.connect(j.path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE events SET event_type='X'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM events")
    con.close()
    j.close()


def test_chain_links_and_seq() -> None:
    """Expected: seq increments and each event links to the previous hash."""
    j = JournalStore("run-y")
    a = j.append(EventType.RUN_STARTED, T0, {"a": 1}, payload_type="X")
    b = j.append(EventType.RUN_COMPLETED, T0, {"b": 2}, payload_type="X")
    assert (a.seq, b.seq) == (1, 2) and b.prev_event_hash == a.event_hash
    assert a.prev_event_hash == "sha256:" + "0" * 64
    assert [e["seq"] for e in read_events("run-y")] == [1, 2]
    j.close()


def test_runs_are_separate() -> None:
    """Edge: two runs in one file keep separate chains."""
    j1, j2 = JournalStore("r1"), JournalStore("r2")
    j1.append(EventType.RUN_STARTED, T0, {}, payload_type="X")
    e = j2.append(EventType.RUN_STARTED, T0, {}, payload_type="X")
    assert e.seq == 1 and len(read_events("r1")) == 1
    j1.close()
    j2.close()
