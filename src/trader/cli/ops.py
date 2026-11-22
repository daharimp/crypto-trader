"""``trader ops health``: read-only bot health check for the server watchdog (ADR-047).

The watchdog script (``scripts/ops/watchdog.sh``) saves ``docker compose ps`` and recent logs
under ``data/ops/`` and runs this command in the ``cli`` container. It writes
``data/ops/health.json`` and, with ``--alert``, sends de-duplicated alerts to the owner's
phone. It never restarts a service, edits a setting or places an order.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer

from trader.common.paths import configs_root, data_root
from trader.ops.health import (
    Problem,
    alerts_to_send,
    build_snapshot,
    check_containers,
    check_logs,
    check_perps,
    check_spot,
    parse_compose_ps,
)

app = typer.Typer(help="Server health checks (ADR-047).", no_args_is_help=True)


def _stop_pct(config_file: str) -> Any:
    from trader.perps.params import load_perps_params

    return load_perps_params(configs_root(), file_name=config_file).stop_loss_pct_of_collateral


def _read(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def run_checks(
    containers: Path | None, logs: Path | None, now: datetime
) -> tuple[list[Problem], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Run every check.

    Args:
        containers (Path | None): Saved ``docker compose ps --format json`` output.
        logs (Path | None): Saved recent ``docker compose logs`` output.
        now (datetime): Current time.

    Returns:
        tuple: Problems, account summaries, and parsed container rows.
    """
    from trader.cli.perps import ACCOUNTS, account_paths
    from trader.risk.controls import PersistedKillSwitch

    problems: list[Problem] = []
    rows: list[dict[str, Any]] = []
    if containers is not None:
        text = _read(containers)
        try:
            if text is None:
                raise ValueError("missing")
            rows = parse_compose_ps(text)
            problems += check_containers(rows)
        except ValueError:
            problems.append(Problem("containers:unknown", "alert", "container list unreadable"))
    if logs is not None:
        problems += check_logs(_read(logs) or "")
    root = data_root()
    spot_problems, spot = check_spot(root, now)
    accounts = {name: (account_paths(root, name)[0], cfg[0]) for name, cfg in ACCOUNTS.items()}
    perps_problems, perps = check_perps(accounts, _stop_pct, now)
    problems += spot_problems + perps_problems
    if PersistedKillSwitch().is_engaged():
        problems.append(Problem("killswitch", "alert", "the kill switch is engaged"))
    return problems, spot + perps, rows


@app.command("health")
def health(
    containers: Path | None = typer.Option(None, help="docker compose ps --format json output."),
    logs: Path | None = typer.Option(None, help="Recent docker compose logs output."),
    commit: str = typer.Option("", help="Deployed git commit, recorded in the snapshot."),
    alert: bool = typer.Option(False, help="Send new or changed problems to the phone."),
    remind_hours: float = typer.Option(12.0, help="Repeat a lasting problem this often."),
) -> None:
    """Check the paper bots and write data/ops/health.json; optionally alert on problems."""
    now = datetime.now(UTC)
    problems, summaries, rows = run_checks(containers, logs, now)
    out_dir = data_root() / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot(
        problems,
        summaries,
        now,
        commit=commit or None,
        containers=[
            {k: r.get(k) for k in ("Service", "State", "Status", "ExitCode")} for r in rows
        ],
    )
    (out_dir / "health.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    if alert:
        from trader.session.alerts import Alerter

        state_file = out_dir / "watchdog-state.json"
        previous = json.loads(state_file.read_text()) if state_file.exists() else {}
        messages, state = alerts_to_send(previous, problems, now, timedelta(hours=remind_hours))
        if messages:
            Alerter.from_env("[watchdog]").send("\n".join(messages))
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    status = "OK" if snapshot["ok"] else "PROBLEMS"
    typer.echo(f"{status}: {len(problems)} finding(s)")
    for p in problems:
        typer.echo(f"  {p.severity}: {p.message}")
