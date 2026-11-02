"""``trader backtest run``."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from trader.backtest.runner import run_backtest

from .common import utc_option

app = typer.Typer(help="Run research backtests.", no_args_is_help=True)


@app.command("run")
def run(
    profile: Path = typer.Option(..., "--profile"),
    datasets: str = typer.Option(..., "--datasets", help="Comma-separated dataset IDs."),
    strategy: str = typer.Option(..., "--strategy"),
    timeframe: str = typer.Option(..., "--timeframe"),
    experiment: Path | None = typer.Option(None, "--experiment"),
    cost_scenario: str | None = typer.Option(None, "--cost-scenario"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    eligibility_datasets: str | None = typer.Option(
        None, "--eligibility-datasets", help="Comma-separated 1d datasets for eligibility."
    ),
) -> None:
    """Run a backtest; print the run ID and report path. Exit 3 if blocked."""
    res = run_backtest(
        profile,
        [d.strip() for d in datasets.split(",") if d.strip()],
        strategy,
        timeframe,
        experiment,
        cost_scenario,
        utc_option(start),
        utc_option(end),
        command="trader " + " ".join(sys.argv[1:]),
        eligibility_datasets=[
            d.strip() for d in (eligibility_datasets or "").split(",") if d.strip()
        ]
        or None,
    )
    typer.echo(f"run_id: {res.run_id}")
    if res.report_path:
        typer.echo(f"report: {res.report_path}")
    else:
        typer.echo(res.message, err=True)
    raise typer.Exit(res.exit_code)
