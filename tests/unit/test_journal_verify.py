"""T-38: hash chain verifies; tampering is detected (exit 4)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests.conftest import small_run
from trader.journal.verify import verify


def _tampered_copy(src: Path, dst: Path, run_id: str) -> None:
    """Copy the journal, drop the triggers, and edit one payload."""
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst)
    s.backup(d)
    s.close()
    d.execute("DROP TRIGGER events_no_update")
    row = d.execute(
        "SELECT seq, payload_json FROM events WHERE run_id=? AND event_type='ORDER_FILLED' LIMIT 1",
        (run_id,),
    ).fetchone()
    payload = json.loads(row[1])
    payload["average_fill_price"] = "1"
    d.execute(
        "UPDATE events SET payload_json=? WHERE run_id=? AND seq=?",
        (json.dumps(payload), run_id, row[0]),
    )
    d.commit()
    d.close()


def test_t38_clean_then_tampered(tmp_path: Path) -> None:
    """T-38: clean run verifies; a tampered copy fails with JOURNAL_INTEGRITY_FAILED."""
    r = small_run()
    res = verify(r.run_id)
    assert res.ok and res.summary().startswith("OK ") and res.n_orders > 0
    src = Path(__import__("os").environ["TRADER_DATA_DIR"]) / "journal" / "journal.sqlite"
    bad = tmp_path / "tampered.sqlite"
    _tampered_copy(src, bad, r.run_id)
    res2 = verify(r.run_id, bad)
    assert not res2.ok and "event hash mismatch" in " ".join(res2.errors)
    assert res2.summary().startswith("JOURNAL_INTEGRITY_FAILED")


def test_unknown_run_fails() -> None:
    """Failure: verifying a run with no events fails."""
    assert not verify("run-nope").ok
