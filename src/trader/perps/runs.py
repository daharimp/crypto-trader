"""Archive of finished paper perps runs, so a reset never loses a run's record (ADR-041).

A "run" is one paper account from its ``ACCOUNT_STARTED`` until it is reset. Resetting used to
mean moving or deleting ``data/state/<stem>.json`` by hand, which kept no equity curve and no
summary, and left the old run's trades mixed into the live event log. ``archive_run`` instead
moves the run's state file, event log and equity log into its own folder and writes a
``summary.json`` beside them (start and final equity, P&L, peak, largest drop, trades, stops,
liquidations, fees, settings). Nothing is deleted: every file is moved, never removed.

Layout: ``data/archive/perps/<stem>/<started>__<ended>/{state.json, events.jsonl,
equity.jsonl, summary.json}``. Paper only: nothing here trades or reads a key.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .history import read_history

SUMMARY = "summary.json"
_SAFE = re.compile(r"[^0-9A-Za-z]+")


class RunArchiveError(RuntimeError):
    """The run cannot be archived (nothing to archive, or the target already exists)."""


def _dec(x: Any) -> Decimal | None:
    try:
        return None if x is None else Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None


def _stamp(iso: str | None) -> str:
    """A folder-safe UTC stamp such as ``20261119T0644Z`` from an ISO time."""
    if not iso:
        return "unknown"
    try:
        return datetime.fromisoformat(iso).astimezone(UTC).strftime("%Y%m%dT%H%MZ")
    except ValueError:
        return _SAFE.sub("", iso)[:20] or "unknown"


def summarize(state: dict[str, Any], events_path: Path | None) -> dict[str, Any]:
    """
    Plain summary of one run from its saved state and (optionally) its event log.

    Args:
        state (dict[str, Any]): Parsed session state file (``meta`` and ``account``).
        events_path (Path | None): The run's event log; trade counts are left out when None
            or missing.

    Returns:
        dict[str, Any]: Settings, start and final equity, P&L in dollars and percent, peak,
        largest drop, and (with a log) trades, wins, losses, stops and liquidations. Final
        equity is the last recorded mark, so it includes any position still open then.
    """
    meta, acct = state.get("meta", {}), state.get("account", {})
    start = _dec(meta.get("start_equity_usd"))
    final = _dec(meta.get("equity_usd", acct.get("cash_usd")))
    out: dict[str, Any] = {
        "signal": meta.get("signal"),
        "timeframe": meta.get("timeframe"),
        "trend_timeframe": meta.get("trend_timeframe"),
        "config_version": meta.get("config_version"),
        "started_at": meta.get("started_at"),
        "last_cycle_utc": meta.get("last_cycle_utc"),
        "bars_processed": meta.get("cycles"),
        "start_equity_usd": None if start is None else str(start),
        "final_equity_usd": None if final is None else str(final),
        "pnl_usd": None,
        "pnl_pct": None,
        "peak_equity_usd": meta.get("peak_equity_usd"),
        "max_drawdown_pct": meta.get("max_drawdown_pct"),
        "fees_paid_usd": acct.get("fees_paid_usd"),
        "open_positions_at_end": sorted(acct.get("positions", {})),
    }
    if start is not None and final is not None:
        out["pnl_usd"] = str((final - start).quantize(Decimal("0.01")))
        if start > 0:
            out["pnl_pct"] = str(((final - start) / start * 100).quantize(Decimal("0.01")))
    if events_path is not None and events_path.exists():
        trades = read_history(events_path)["trades"]
        nets = [_dec(t.get("pnl_usd")) for t in trades]
        out.update(
            trades_closed=len(trades),
            wins=sum(1 for n in nets if n is not None and n > 0),
            losses=sum(1 for n in nets if n is not None and n <= 0),
            stops=sum(1 for t in trades if t.get("reason") == "STOP_LOSS"),
            liquidations=sum(1 for t in trades if t.get("liquidated")),
        )
    return out


def archive_run(
    state_path: Path,
    events_path: Path,
    equity_path: Path | None,
    archive_dir: Path,
    reason: str,
    now: datetime,
) -> Path:
    """
    Move a finished run into its own archive folder and write its summary.

    The live state file, event log and equity log are moved (not copied) so the next start
    begins a fresh run with empty logs. Stop the account first: a session still running in
    memory would otherwise write the old account back (``PerpsSession`` refuses to, ADR-041).

    Args:
        state_path (Path): The account's ``data/state/<stem>.json``.
        events_path (Path): The account's event log.
        equity_path (Path | None): The account's per-bar equity log, if it keeps one.
        archive_dir (Path): ``data/archive/perps/<stem>``.
        reason (str): Why the run ends (kept in the summary).
        now (datetime): Archive time (UTC).

    Returns:
        Path: The new run folder.

    Raises:
        RunArchiveError: If there is no saved run, the reason is empty, or the folder exists.
    """
    if not reason.strip():
        raise RunArchiveError("a reason is required, e.g. --reason 'switching signal'")
    if not state_path.exists():
        raise RunArchiveError(f"no saved run at {state_path}; nothing to archive")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    meta = state.get("meta", {})
    ended = meta.get("last_cycle_utc") or now.isoformat()
    run_dir = archive_dir / f"{_stamp(meta.get('started_at'))}__{_stamp(ended)}"
    if run_dir.exists():
        raise RunArchiveError(f"{run_dir} already exists; not overwriting an archived run")
    summary = summarize(state, events_path)
    summary.update(
        run=run_dir.name,
        ended_at=ended,
        archived_at=now.astimezone(UTC).isoformat(),
        reason=reason.strip(),
    )
    run_dir.mkdir(parents=True)
    # Reason: summary first, so a crash mid-way leaves a readable folder, never a lost run;
    # each move is a rename within the data volume, so a file is never half-copied.
    (run_dir / SUMMARY).write_text(json.dumps(summary, indent=1, sort_keys=True), "utf-8")
    for src, name in ((events_path, "events.jsonl"), (equity_path, "equity.jsonl")):
        if src is not None and src.exists():
            os.replace(src, run_dir / name)
    os.replace(state_path, run_dir / "state.json")
    return run_dir


def list_runs(
    archive_dir: Path, state_dir: Path | None = None, stem: str = ""
) -> list[dict[str, Any]]:
    """
    Every archived run of an account, oldest first, plus older hand-moved state files.

    Before ADR-041 the RUNBOOK reset an account with ``mv <stem>.json <stem>-<date>.json``.
    Those files have no equity curve, but their saved ``meta`` still holds the start, final
    and peak equity, so they are listed too (``legacy: true``) when ``state_dir`` is given.

    Args:
        archive_dir (Path): ``data/archive/perps/<stem>``.
        state_dir (Path | None): ``data/state``, to include legacy hand-moved files.
        stem (str): The account's file stem, e.g. ``perps-paper``.

    Returns:
        list[dict]: One summary per run; unreadable files are reported with ``error``.
    """
    runs: list[dict[str, Any]] = []
    if archive_dir.exists():
        for d in sorted(p for p in archive_dir.iterdir() if p.is_dir()):
            try:
                runs.append(json.loads((d / SUMMARY).read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                runs.append({"run": d.name, "error": f"unreadable summary: {exc}"})
    if state_dir is not None and stem and state_dir.exists():
        for f in sorted(state_dir.glob(f"{stem}-*.json")):
            try:
                s = summarize(json.loads(f.read_text(encoding="utf-8")), None)
            except (OSError, ValueError, AttributeError) as exc:
                runs.append({"run": f.name, "legacy": True, "error": str(exc)})
                continue
            runs.append({**s, "run": f.name, "legacy": True})
    return sorted(runs, key=lambda r: str(r.get("started_at") or ""))
