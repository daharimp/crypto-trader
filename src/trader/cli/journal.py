"""``trader journal verify``."""

from __future__ import annotations

import typer

from trader.journal.verify import verify as verify_run

from .common import EXIT_INTEGRITY

app = typer.Typer(help="Verify the append-only journal.", no_args_is_help=True)


@app.command("verify")
def verify(run_id: str = typer.Argument(...)) -> None:
    """Recompute the hash chain and D-36 traceability. Exit 4 on any mismatch."""
    res = verify_run(run_id)
    typer.echo(res.summary())
    raise typer.Exit(0 if res.ok else EXIT_INTEGRITY)
