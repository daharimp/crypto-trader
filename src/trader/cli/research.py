"""``trader research compare``: strategies x windows x costs, with a random-entry control."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .common import EXIT_BLOCKED, EXIT_INVALID, utc_option

app = typer.Typer(help="Research tools (backtest environment only).", no_args_is_help=True)


def _split(text: str | None) -> list[str]:
    """
    Split a comma-separated option.

    Args:
        text (str | None): Option text.

    Returns:
        list[str]: Items.
    """
    return [x.strip() for x in (text or "").split(",") if x.strip()]


@app.command("compare")
def compare(
    profile: Path = typer.Option(..., "--profile"),
    datasets: str = typer.Option(..., "--datasets", help="Datasets at --timeframe."),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    strategies: str = typer.Option(
        "sma_trend,tsmom,mean_reversion,volatility_breakout", "--strategies"
    ),
    cost_scenarios: str = typer.Option("base,base_maker", "--cost-scenarios"),
    windows: int = typer.Option(4, "--windows"),
    random_seeds: int = typer.Option(10, "--random-seeds"),
    eligibility_datasets: str | None = typer.Option(None, "--eligibility-datasets"),
    out: Path = typer.Option(Path("data/research/compare"), "--out"),
    timeframe: str = typer.Option("4h", "--timeframe", help="Decision timeframe: 1h or 4h."),
    reference: str = typer.Option(
        "sma_trend", "--reference", help="Strategy the random control is matched to."
    ),
) -> None:
    """Run the comparison and write compare.json and compare.md to --out."""
    from trader.common.paths import configs_root
    from trader.research.compare import CompareConfig, Comparison, render_markdown

    s, e = utc_option(start), utc_option(end)
    assert s and e
    cfg = CompareConfig(
        profile=profile,
        datasets=_split(datasets),
        start=s,
        end=e,
        strategies=_split(strategies),
        cost_scenarios=_split(cost_scenarios),
        windows=windows,
        random_seeds=random_seeds,
        eligibility_datasets=_split(eligibility_datasets) or None,
        configs_root=configs_root(),
        timeframe=timeframe,
        reference_strategy=reference,
    )
    out.mkdir(parents=True, exist_ok=True)
    try:
        result = Comparison(cfg, out).run()
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INVALID) from None
    (out / "compare.json").write_text(json.dumps(result, indent=1, default=str))
    md = render_markdown(result)
    (out / "compare.md").write_text(md)
    typer.echo(md)


@app.command("snapshot")
def snapshot(
    history_dir: Path = typer.Option(
        Path("data/long"), "--history-dir", help="Folder with <coin>_usd_4h.csv history files."
    ),
    capital: float = typer.Option(2500.0, "--capital", help="Dollars to express results in."),
    out: Path = typer.Option(Path("data/research/snapshot"), "--out"),
) -> None:
    """Live market state per coin, compared with what happened after similar states (ADR-029).

    Reads public Kraken data only; places no orders. Writes snapshot.json and snapshot.md.
    Exit 3 if no coin's live data could be read.
    """
    from trader.research.snapshot import render_markdown, take_snapshot

    if capital <= 0:
        typer.echo("--capital must be positive", err=True)
        raise typer.Exit(EXIT_INVALID)
    snap = take_snapshot(history_dir, capital)
    if not snap.states:
        typer.echo(f"no live data: {snap.errors}", err=True)
        raise typer.Exit(EXIT_BLOCKED)
    out.mkdir(parents=True, exist_ok=True)
    (out / "snapshot.json").write_text(snap.to_json())
    md = render_markdown(snap)
    (out / "snapshot.md").write_text(md)
    typer.echo(md)
