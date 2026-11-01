"""``trader killswitch status|engage|disengage`` (persisted, D-35)."""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from trader.risk.controls import PersistedKillSwitch

from .common import EXIT_INVALID

app = typer.Typer(help="Persisted kill switch (governs paper sessions).", no_args_is_help=True)


@app.command("status")
def status() -> None:
    """Print the current state and how many changes were recorded."""
    ks = PersistedKillSwitch()
    s = ks.state()
    n = len(ks.store.killswitch_history())
    if s is None:
        typer.echo(f"state: disengaged (initial)  history: {n}")
        return
    typer.echo(
        f"state: {s.state}  changed_by: {s.changed_by}  at: "
        f"{s.changed_at_utc:%Y-%m-%dT%H:%M:%SZ}  reason: {s.reason}  history: {n}"
    )


@app.command("engage")
def engage(reason: str = typer.Option(..., "--reason")) -> None:
    """Engage: blocks all new orders in paper sessions."""
    if not reason.strip():
        typer.echo("a reason is required", err=True)
        raise typer.Exit(EXIT_INVALID)
    s = PersistedKillSwitch().engage(reason, datetime.now(UTC))
    typer.echo(f"state: {s.state}  reason: {s.reason}")


@app.command("disengage")
def disengage(reason: str = typer.Option(..., "--reason")) -> None:
    """Disengage (owner command with reason; recorded as changed_by=owner)."""
    if not reason.strip():
        typer.echo("a reason is required", err=True)
        raise typer.Exit(EXIT_INVALID)
    s = PersistedKillSwitch().disengage(reason, datetime.now(UTC))
    typer.echo(f"state: {s.state}  changed_by: {s.changed_by}  reason: {s.reason}")
