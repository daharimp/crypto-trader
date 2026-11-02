"""Append-only, hash-chained SQLite journal (§7.11, ADR-018)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trader.common.canonical import canonical_json, to_canonical_obj
from trader.common.clock import format_utc, parse_utc
from trader.common.hashing import GENESIS_HASH, sha256_tag
from trader.common.paths import data_path
from trader.common.revision import code_revision
from trader.domain.enums import EventType
from trader.domain.events import TradeEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL,
  event_type TEXT NOT NULL, event_time_utc TEXT NOT NULL, recorded_at_utc TEXT NOT NULL,
  cycle_id TEXT, correlation_id TEXT, payload_type TEXT NOT NULL,
  payload_schema_version TEXT NOT NULL, payload_json TEXT NOT NULL,
  code_revision TEXT NOT NULL, config_hash TEXT NOT NULL,
  prev_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
  PRIMARY KEY (run_id, seq));
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
"""


class JournalWriteError(RuntimeError):
    """Raised when an event cannot be committed (triggers journal-before-act halts)."""


def hash_content(prev_hash: str, content: dict[str, Any]) -> str:
    """
    Compute ``sha256(prev_event_hash + "\\n" + canonical_json(content))``.

    Args:
        prev_hash (str): Previous event hash.
        content (dict[str, Any]): Hashed fields.

    Returns:
        str: Event hash.
    """
    return sha256_tag(prev_hash + "\n" + canonical_json(content))


def event_content(e: dict[str, Any]) -> dict[str, Any]:
    """
    Select the hashed fields (excludes run_id, recorded_at_utc, event_hash).

    Args:
        e (dict[str, Any]): Event fields.

    Returns:
        dict[str, Any]: Content to hash.
    """
    keys = (
        "seq",
        "event_id",
        "event_type",
        "event_time_utc",
        "cycle_id",
        "correlation_id",
        "payload_type",
        "payload_schema_version",
        "payload",
        "code_revision",
        "config_hash",
    )
    return {k: e[k] for k in keys}


class JournalStore:
    """Writes one run's events; each event is its own committed transaction."""

    def __init__(self, run_id: str, path: Path | None = None) -> None:
        """
        Open the journal for a run.

        Args:
            run_id (str): Run ID.
            path (Path | None): SQLite path; defaults to ``data/journal/journal.sqlite``.
        """
        self.run_id = run_id
        self.path = path or data_path("journal", "journal.sqlite")
        self.seq = 0
        self.prev_hash = GENESIS_HASH
        self.config_hash = ""
        # Reason (ADR-019): one persistent connection in WAL mode. Every event is still its
        # own committed transaction (journal-before-act holds), but without an fsync per
        # event, which made long backtests ~20x slower.
        self._con = sqlite3.connect(self.path, timeout=30)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        with self._con:
            self._con.executescript(SCHEMA)

    def close(self) -> None:
        """Checkpoint the WAL into the main file and close the connection."""
        try:
            self._con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            self._con.close()

    def append(
        self,
        event_type: EventType,
        event_time: datetime,
        payload: Any,
        cycle_id: str | None = None,
        correlation_id: str | None = None,
        payload_type: str | None = None,
    ) -> TradeEvent:
        """
        Append and commit one event.

        Args:
            event_type (EventType): Type.
            event_time (datetime): Simulated (backtest) time.
            payload (Any): Pydantic model or dict.
            cycle_id (str | None): Cycle ID.
            correlation_id (str | None): Correlation ID.
            payload_type (str | None): Payload type name (defaults to the model class name).

        Returns:
            TradeEvent: The committed event.

        Raises:
            JournalWriteError: If the write fails.
        """
        body = to_canonical_obj(payload)
        fields: dict[str, Any] = {
            "seq": self.seq + 1,
            "event_id": f"evt-{self.seq + 1:06d}",
            "event_type": event_type.value,
            "event_time_utc": format_utc(event_time),
            "cycle_id": cycle_id,
            "correlation_id": correlation_id,
            "payload_type": payload_type or type(payload).__name__,
            "payload_schema_version": "1.0.0",
            "payload": body,
            "code_revision": code_revision(),
            "config_hash": self.config_hash,
        }
        ev_hash = hash_content(self.prev_hash, event_content(fields))
        recorded = datetime.now(UTC)
        try:
            self._write(fields, recorded, ev_hash)
        except (sqlite3.Error, OSError) as exc:
            raise JournalWriteError(str(exc)) from exc
        self.seq += 1
        prev, self.prev_hash = self.prev_hash, ev_hash
        return TradeEvent(
            schema_version="1.0.0",
            run_id=self.run_id,
            recorded_at_utc=recorded,
            event_time_utc=event_time,
            event_type=event_type,
            prev_event_hash=prev,
            event_hash=ev_hash,
            **{
                k: fields[k]
                for k in (
                    "seq",
                    "event_id",
                    "cycle_id",
                    "correlation_id",
                    "payload_type",
                    "payload_schema_version",
                    "payload",
                    "code_revision",
                    "config_hash",
                )
            },
        )

    def _write(self, f: dict[str, Any], recorded: datetime, ev_hash: str) -> None:
        """
        Insert one row in its own transaction.

        Args:
            f (dict[str, Any]): Fields.
            recorded (datetime): Wall-clock time.
            ev_hash (str): Event hash.
        """
        with self._con as con:
            con.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    f["seq"],
                    f["event_id"],
                    f["event_type"],
                    f["event_time_utc"],
                    format_utc(recorded),
                    f["cycle_id"],
                    f["correlation_id"],
                    f["payload_type"],
                    f["payload_schema_version"],
                    canonical_json(f["payload"]),
                    f["code_revision"],
                    f["config_hash"],
                    self.prev_hash,
                    ev_hash,
                ),
            )


def read_events(run_id: str, path: Path | None = None) -> list[dict[str, Any]]:
    """
    Read a run's events in sequence order.

    Args:
        run_id (str): Run ID.
        path (Path | None): Journal path.

    Returns:
        list[dict[str, Any]]: Event rows with parsed payloads.
    """
    p = path or data_path("journal", "journal.sqlite")
    if not p.exists():
        return []
    with closing(sqlite3.connect(p)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json"))
        d["event_time"] = parse_utc(d["event_time_utc"])
        out.append(d)
    return out
