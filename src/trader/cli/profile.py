"""``trader profile validate|compile``."""

from __future__ import annotations

from pathlib import Path

import typer

from trader.domain.enums import Environment
from trader.evaluation.report import non_approved_values
from trader.profiles.compiler import compile_bundle, exit_code

app = typer.Typer(help="Validate and compile trading profiles.", no_args_is_help=True)


def _print_summary(compiled) -> None:  # type: ignore[no-untyped-def]
    """
    Print a human-readable compile summary.

    Args:
        compiled (CompiledProfile): Compiled profile.
    """
    typer.echo(f"runnable: {str(compiled.runnable).lower()}")
    typer.echo(f"environment: {compiled.environment.value}")
    typer.echo(f"config_hash: {compiled.config_hash}")
    if compiled.experiment_id:
        typer.echo(f"experiment: {compiled.experiment_id}")
    typer.echo(f"errors: {len(compiled.errors)}")
    for e in compiled.errors:
        typer.echo(f"  - {e}")
    refs = sorted({b.ref for b in compiled.blockers})
    typer.echo(f"blockers: {len(compiled.blockers)} ({', '.join(refs) or 'none'})")
    for b in compiled.blockers:
        typer.echo(f"  - {b.ref} {b.field}: {b.reason}")
    na = non_approved_values(compiled)
    typer.echo(f"non-approved values in use: {len(na)}")
    for v in na:
        typer.echo(f"  - [{v['provenance']}] {v['field']} = {v['value']} ({v['ref']})")


@app.command("validate")
def validate(
    profile: Path = typer.Argument(..., help="TradingProfile YAML."),
    environment: Environment = typer.Option(Environment.BACKTEST, "--environment", "-e"),
    experiment: Path | None = typer.Option(None, "--experiment", help="Experiment set (backtest)."),
) -> None:
    """Compile and print a summary. Exit 0 runnable, 2 invalid, 3 blocked (UD IDs listed)."""
    compiled = compile_bundle(profile, environment, experiment).compiled
    _print_summary(compiled)
    raise typer.Exit(exit_code(compiled))


@app.command("compile")
def compile_cmd(
    profile: Path = typer.Argument(..., help="TradingProfile YAML."),
    environment: Environment = typer.Option(Environment.BACKTEST, "--environment", "-e"),
    experiment: Path | None = typer.Option(None, "--experiment"),
    out: Path | None = typer.Option(None, "--out", help="Write CompiledProfile JSON here."),
) -> None:
    """Write the CompiledProfile JSON (stdout or --out)."""
    compiled = compile_bundle(profile, environment, experiment).compiled
    text = compiled.model_dump_json(indent=2)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)
    raise typer.Exit(exit_code(compiled))
