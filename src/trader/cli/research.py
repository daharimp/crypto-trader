"""``trader research compare``: strategies x windows x costs, with a random-entry control."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .common import EXIT_INVALID, utc_option

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
