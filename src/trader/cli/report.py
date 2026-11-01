"""``trader report show``."""

from __future__ import annotations

from enum import StrEnum

import typer

from trader.common.paths import data_root

from .common import EXIT_INVALID

app = typer.Typer(help="Show backtest reports.", no_args_is_help=True)


class Fmt(StrEnum):
    """Report formats."""

    md = "md"
    json = "json"


@app.command("show")
def show(run_id: str = typer.Argument(...), fmt: Fmt = typer.Option(Fmt.md, "--format")) -> None:
    """Print a run's report."""
    path = data_root() / "reports" / run_id / f"report.{fmt.value}"
    if not path.exists():
        typer.echo(f"no report for {run_id}", err=True)
        raise typer.Exit(EXIT_INVALID)
    typer.echo(path.read_text())
