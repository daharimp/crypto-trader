"""Archived paper perps runs (ADR-041): a reset keeps the run's record instead of wiping it."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS
from tests.unit.test_perps_session import DOWN, Feed, _rows, _session
from trader.cli.main import app
from trader.perps.runs import RunArchiveError, archive_run, list_runs
from trader.perps.session import SessionStateError

NOW = datetime(2026, 11, 19, 7, 0, tzinfo=UTC)


def _ran(tmp_path: Path, bars: int = 3) -> tuple[Feed, Path]:
    """A session that opened shorts and processed a few more falling bars."""
    feed = Feed(DOWN)
    equity = tmp_path / "logs" / "equity.jsonl"
    s, _ = _session(tmp_path, feed, equity_path=equity)
    s.cycle(feed.now())
    for _ in range(bars):
        feed.closes.append(feed.closes[-1] * 0.99)
        s.cycle(feed.now())
    return feed, equity


def _archive(tmp_path: Path, reason: str = "switching signal") -> Path:
    return archive_run(
        tmp_path / "state" / "perps-paper.json",
        tmp_path / "logs" / "events.jsonl",
        tmp_path / "logs" / "equity.jsonl",
        tmp_path / "archive" / "perps-paper",
        reason,
        NOW,
    )


def test_session_records_one_equity_point_per_processed_bar(tmp_path: Path) -> None:
    _, equity = _ran(tmp_path, bars=3)
    points = [json.loads(x) for x in equity.read_text().splitlines()]
    assert len(points) == 4  # the first bar plus three more
    assert all({"at_utc", "equity_usd", "peak_equity_usd"} <= set(p) for p in points)
    assert [p["at_utc"] for p in points] == sorted(p["at_utc"] for p in points)


def test_archive_moves_every_file_and_writes_an_honest_summary(tmp_path: Path) -> None:
    _ran(tmp_path)
    state = json.loads((tmp_path / "state" / "perps-paper.json").read_text())
    run = _archive(tmp_path)
    assert sorted(p.name for p in run.iterdir()) == [
        "equity.jsonl",
        "events.jsonl",
        "state.json",
        "summary.json",
    ]
    # Moved, not copied: the next start begins with no state and empty logs.
    assert not (tmp_path / "state" / "perps-paper.json").exists()
    assert not (tmp_path / "logs" / "events.jsonl").exists()
    assert not (tmp_path / "logs" / "equity.jsonl").exists()
    s = json.loads((run / "summary.json").read_text())
    meta = state["meta"]
    assert s["start_equity_usd"] == meta["start_equity_usd"]
    assert s["final_equity_usd"] == meta["equity_usd"]
    assert s["peak_equity_usd"] == meta["peak_equity_usd"]
    assert s["max_drawdown_pct"] == meta["max_drawdown_pct"]
    assert s["reason"] == "switching signal" and s["archived_at"] == NOW.isoformat()
    assert s["open_positions_at_end"] == ["ETH", "SOL"] and s["trades_closed"] == 0
    assert run.name.startswith(s["run"][:14]) and "__" in run.name


def test_a_new_run_after_the_archive_starts_fresh(tmp_path: Path) -> None:
    feed, equity = _ran(tmp_path)
    _archive(tmp_path)
    s, _ = _session(tmp_path, feed, equity_path=equity)
    assert s.acct is None
    events = s.cycle(feed.now() + timedelta(hours=4))
    assert events[0]["event"] == "ACCOUNT_STARTED"
    assert len(equity.read_text().splitlines()) == 1


def test_running_session_refuses_to_resurrect_an_archived_run(tmp_path: Path) -> None:
    feed = Feed(DOWN)
    s, _ = _session(tmp_path, feed, equity_path=tmp_path / "logs" / "equity.jsonl")
    s.cycle(feed.now())
    _archive(tmp_path)
    feed.closes.append(feed.closes[-1] * 0.99)
    with pytest.raises(SessionStateError, match="archived or moved"):
        s.cycle(feed.now())
    # Neither the state nor the old run's events reappear.
    assert not (tmp_path / "state" / "perps-paper.json").exists()
    assert not (tmp_path / "logs" / "events.jsonl").exists()


def test_archive_failures(tmp_path: Path) -> None:
    with pytest.raises(RunArchiveError, match="nothing to archive"):
        _archive(tmp_path)
    _ran(tmp_path, bars=0)
    with pytest.raises(RunArchiveError, match="reason"):
        _archive(tmp_path, reason="  ")
    first = _archive(tmp_path)
    # Same start and end stamps would overwrite: refused, nothing moved.
    first_state = (first / "state.json").read_text()
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "perps-paper.json").write_text(first_state)
    with pytest.raises(RunArchiveError, match="already exists"):
        _archive(tmp_path)
    assert (tmp_path / "state" / "perps-paper.json").exists()


def test_list_runs_includes_hand_moved_legacy_files(tmp_path: Path) -> None:
    _ran(tmp_path)
    state = json.loads((tmp_path / "state" / "perps-paper.json").read_text())
    _archive(tmp_path)
    # An older run moved aside the RUNBOOK's old way, started earlier, peaked at $2,801.
    legacy = json.loads(json.dumps(state))
    legacy["meta"].update(
        started_at="2025-11-01T00:00:00+00:00", peak_equity_usd="2801", equity_usd="2650"
    )
    (tmp_path / "state" / "perps-paper-20251110.json").write_text(json.dumps(legacy))
    (tmp_path / "state" / "perps-paper-broken.json").write_text("{nope")
    (tmp_path / "state" / "perps-degen-20251110.json").write_text(json.dumps(legacy))
    runs = list_runs(tmp_path / "archive" / "perps-paper", tmp_path / "state", "perps-paper")
    assert len(runs) == 3  # archived + legacy + unreadable; the degen file is not listed
    good = [r for r in runs if "error" not in r]
    assert good[0]["legacy"] and good[0]["peak_equity_usd"] == "2801"
    assert good[0]["pnl_usd"] == "1650.00"  # fixture start is $1,000
    assert not good[1].get("legacy") and good[1]["reason"] == "switching signal"
    assert any("error" in r for r in runs)
    assert list_runs(tmp_path / "nowhere") == []


def test_cli_reset_and_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import trader.ui.data as ui_data

    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    long_down = [100 * 0.995**i for i in range(200)]
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", lambda symbol, tf: _rows(long_down))
    r = CliRunner().invoke(app, ["perps", "paper", "reset", "--reason", "x"])
    assert r.exit_code == 2 and "nothing to archive" in r.output
    r = CliRunner().invoke(app, ["perps", "paper", "runs"])
    assert r.exit_code == 0 and "no archived main runs" in r.output
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "logs" / "perps-paper-equity.jsonl").exists()
    r = CliRunner().invoke(app, ["perps", "paper", "reset"])
    assert r.exit_code == 2  # --reason is required
    r = CliRunner().invoke(app, ["perps", "paper", "reset", "--reason", "new stop-loss"])
    assert r.exit_code == 0, r.output
    assert "archived main run" in r.output and "fresh run" in r.output
    assert not (tmp_path / "state" / "perps-paper.json").exists()
    r = CliRunner().invoke(app, ["perps", "paper", "runs"])
    assert "tsmom_30d 4h" in r.output and "reason: new stop-loss" in r.output
    assert "not guaranteed" in r.output
    # The degen account is separate: nothing archived there.
    r = CliRunner().invoke(app, ["perps", "paper", "runs", "--account", "degen"])
    assert "no archived degen runs" in r.output
