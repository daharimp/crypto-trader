"""Operational store (``data/state/operational.sqlite``).

Holds the persisted kill switch history (append-only) and the profile compilation registry
used by PV-10.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from trader.domain.killswitch import KillSwitchState

from .clock import format_utc, parse_utc
from .paths import data_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS killswitch_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, state TEXT NOT NULL, changed_at_utc TEXT NOT NULL,
  changed_by TEXT NOT NULL, reason TEXT NOT NULL, trigger TEXT);
CREATE TRIGGER IF NOT EXISTS ks_no_update BEFORE UPDATE ON killswitch_history
  BEGIN SELECT RAISE(ABORT, 'killswitch history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ks_no_delete BEFORE DELETE ON killswitch_history
  BEGIN SELECT RAISE(ABORT, 'killswitch history is append-only'); END;
CREATE TABLE IF NOT EXISTS profile_compilations (
  profile_id TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL,
  first_seen_utc TEXT NOT NULL, PRIMARY KEY (profile_id, version));
CREATE TABLE IF NOT EXISTS activations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL, version INTEGER NOT NULL,
  content_hash TEXT NOT NULL, environment TEXT NOT NULL, activated_at_utc TEXT NOT NULL,
  activated_by TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS act_no_update BEFORE UPDATE ON activations
  BEGIN SELECT RAISE(ABORT, 'activations are append-only'); END;
CREATE TABLE IF NOT EXISTS owner_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, requested_at_utc TEXT NOT NULL,
  reason TEXT NOT NULL, handled_at_utc TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS paper_cycles (
  profile_id TEXT NOT NULL, version INTEGER NOT NULL, decision_time_utc TEXT NOT NULL,
  PRIMARY KEY (profile_id, version, decision_time_utc));
"""


class OperationalStore:
    """SQLite-backed operational state."""

    def __init__(self, path: Path | None = None) -> None:
        """
        Open (and create if needed) the operational store.

        Args:
            path (Path | None): Database path; defaults to ``data/state/operational.sqlite``.
        """
        self.path = path or data_path("state", "operational.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con, con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """
        Open a connection.

        Returns:
            sqlite3.Connection: New connection.
        """
        # Reason: a running session and CLI commands share this file; wait instead of failing.
        return sqlite3.connect(self.path, timeout=30)

    # --- kill switch -------------------------------------------------------------------
    def killswitch_state(self) -> KillSwitchState | None:
        """
        Return the latest kill-switch state, or None if never changed (disengaged).

        Returns:
            KillSwitchState | None: Latest state row.
        """
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT state, changed_at_utc, changed_by, reason, trigger "
                "FROM killswitch_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return KillSwitchState(
            schema_version="1.0.0",
            state=row[0],
            changed_at_utc=parse_utc(row[1]),
            changed_by=row[2],
            reason=row[3],
            trigger=row[4],
        )

    def killswitch_history(self) -> list[KillSwitchState]:
        """
        Return every kill-switch change, oldest first.

        Returns:
            list[KillSwitchState]: History.
        """
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT state, changed_at_utc, changed_by, reason, trigger "
                "FROM killswitch_history ORDER BY id"
            ).fetchall()
        return [
            KillSwitchState(
                schema_version="1.0.0",
                state=r[0],
                changed_at_utc=parse_utc(r[1]),
                changed_by=r[2],
                reason=r[3],
                trigger=r[4],
            )
            for r in rows
        ]

    def append_killswitch(self, state: KillSwitchState) -> None:
        """
        Append a kill-switch change.

        Args:
            state (KillSwitchState): New state row.
        """
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT INTO killswitch_history (state, changed_at_utc, changed_by, reason, "
                "trigger) VALUES (?, ?, ?, ?, ?)",
                (
                    state.state,
                    format_utc(state.changed_at_utc),
                    state.changed_by,
                    state.reason,
                    state.trigger,
                ),
            )

    # --- PV-10 -------------------------------------------------------------------------
    def check_and_record_profile(
        self, profile_id: str, version: int, content_hash: str, now: datetime
    ) -> str | None:
        """
        Record a profile version's content hash, or return the conflicting stored hash.

        Args:
            profile_id (str): Profile ID.
            version (int): Profile version.
            content_hash (str): Hash of the profile content.
            now (datetime): Time to record on first sight.

        Returns:
            str | None: The previously recorded hash if it differs, else None.
        """
        with closing(self._connect()) as con, con:
            row = con.execute(
                "SELECT content_hash FROM profile_compilations WHERE profile_id=? AND version=?",
                (profile_id, version),
            ).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO profile_compilations VALUES (?, ?, ?, ?)",
                    (profile_id, version, content_hash, format_utc(now)),
                )
                return None
            return None if row[0] == content_hash else str(row[0])

    # --- activation records (BL-028) ---------------------------------------------------
    def record_activation(
        self,
        profile_id: str,
        version: int,
        content_hash: str,
        environment: str,
        now: datetime,
        reason: str,
    ) -> None:
        """
        Append an owner activation record.

        Args:
            profile_id (str): Profile ID.
            version (int): Profile version.
            content_hash (str): Profile content hash at activation.
            environment (str): ``paper`` or ``live``.
            now (datetime): Activation time.
            reason (str): Owner's reason.
        """
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT INTO activations (profile_id, version, content_hash, environment, "
                "activated_at_utc, activated_by, reason) VALUES (?, ?, ?, ?, ?, 'owner', ?)",
                (profile_id, version, content_hash, environment, format_utc(now), reason),
            )

    def has_activation(
        self, profile_id: str, version: int, content_hash: str, environment: str
    ) -> bool:
        """
        Whether this exact profile content was activated for an environment.

        Args:
            profile_id (str): Profile ID.
            version (int): Version.
            content_hash (str): Content hash (any edit invalidates the activation).
            environment (str): Environment.

        Returns:
            bool: True if an activation record matches.
        """
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT 1 FROM activations WHERE profile_id=? AND version=? AND content_hash=? "
                "AND environment=? LIMIT 1",
                (profile_id, version, content_hash, environment),
            ).fetchone()
        return row is not None

    # --- owner requests to a running session (flatten BL-048, breaker reset) ------------
    def request(self, kind: str, reason: str, now: datetime) -> int:
        """
        Queue an owner request (``flatten`` or ``reset_breaker``) for the running session.

        Args:
            kind (str): Request kind.
            reason (str): Owner's reason.
            now (datetime): Request time.

        Returns:
            int: Request ID.
        """
        with closing(self._connect()) as con, con:
            cur = con.execute(
                "INSERT INTO owner_requests (kind, requested_at_utc, reason) VALUES (?, ?, ?)",
                (kind, format_utc(now), reason),
            )
            return int(cur.lastrowid or 0)

    def pending_request(self, kind: str) -> tuple[int, str] | None:
        """
        Return the oldest unhandled request of a kind.

        Args:
            kind (str): Request kind.

        Returns:
            tuple[int, str] | None: ``(id, reason)`` or None.
        """
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT id, reason FROM owner_requests WHERE kind=? AND handled_at_utc IS NULL "
                "ORDER BY id LIMIT 1",
                (kind,),
            ).fetchone()
        return (int(row[0]), str(row[1])) if row else None

    def mark_request_handled(self, request_id: int, now: datetime, outcome: str) -> None:
        """
        Mark a request handled.

        Args:
            request_id (int): Request ID.
            now (datetime): Time.
            outcome (str): What happened.
        """
        with closing(self._connect()) as con, con:
            con.execute(
                "UPDATE owner_requests SET handled_at_utc=?, outcome=? WHERE id=?",
                (format_utc(now), outcome, request_id),
            )

    # --- paper track record --------------------------------------------------------------
    def record_paper_cycle(self, profile_id: str, version: int, decision_time: datetime) -> None:
        """
        Record one completed forward paper cycle (idempotent per decision time).

        Args:
            profile_id (str): Profile ID.
            version (int): Profile version.
            decision_time (datetime): Cycle decision time.
        """
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT OR IGNORE INTO paper_cycles VALUES (?, ?, ?)",
                (profile_id, version, format_utc(decision_time)),
            )

    def paper_cycle_count(self, profile_id: str, version: int) -> int:
        """
        Number of completed forward paper cycles for a profile version.

        Args:
            profile_id (str): Profile ID.
            version (int): Version.

        Returns:
            int: Count.
        """
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM paper_cycles WHERE profile_id=? AND version=?",
                (profile_id, version),
            ).fetchone()
        return int(row[0])
