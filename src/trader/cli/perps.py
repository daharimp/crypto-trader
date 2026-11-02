"""``trader perps validate|prices|backtest``: Jupiter Perps, paper only (ADR-024)."""

from __future__ import annotations

import json

import typer

from trader.data.frames import columns
from trader.data.store import DatasetStore
from trader.perps.backtest import Bar, run_perps_backtest
from trader.perps.params import (
    PerpsConfigUnresolvedError,
    PerpsParams,
    load_perps_file,
    load_perps_params,
)
from trader.perps.prices import PriceUnavailableError, fetch_prices

from .common import EXIT_BLOCKED, EXIT_INVALID

app = typer.Typer(help="Jupiter Perps research, paper only (ADR-024).", no_args_is_help=True)


def _params_or_exit() -> PerpsParams:
    """Load perps parameters or exit 3 (unresolved) / 2 (invalid)."""
    try:
        return load_perps_params()
    except PerpsConfigUnresolvedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_BLOCKED) from None
    except ValueError as exc:
        typer.echo(f"invalid perps config: {exc}", err=True)
        raise typer.Exit(EXIT_INVALID) from None


@app.command("validate")
def validate() -> None:
    """Check configs/perps/jupiter.yaml. Exit 3 lists every unresolved value."""
    params = _params_or_exit()
    typer.echo(f"perps config v{params.version}: all values approved (paper only)")


@app.command("prices")
def prices() -> None:
    """Print current public USD prices from Jupiter (read-only)."""
    try:
        markets: dict[str, str] = {m.market: m.price_mint for m in load_perps_file().markets}
        for market, price in fetch_prices(markets).items():
            typer.echo(f"{market}: {price}")
    except PriceUnavailableError as exc:
        typer.echo(f"PRICE_UNAVAILABLE: {exc}", err=True)
        raise typer.Exit(EXIT_BLOCKED) from None


@app.command("backtest")
def backtest(
    dataset: list[str] = typer.Option(..., "--dataset", help="MARKET=dataset_id, repeatable"),
    fast: int = typer.Option(20, "--fast"),
    slow: int = typer.Option(50, "--slow"),
    long_only: bool = typer.Option(False, "--long-only"),
) -> None:
    """Replay the sma_stance signal through the paper perps account."""
    params = _params_or_exit()
    store = DatasetStore()
    bars: dict[str, list[Bar]] = {}
    for spec in dataset:
        market, _, ds = spec.partition("=")
        if not ds:
            typer.echo(f"expected MARKET=dataset_id, got {spec}", err=True)
            raise typer.Exit(EXIT_INVALID)
        _, df = store.load(ds)
        bars[market] = [
            Bar(t, o, h, lo, c)
            for t, o, h, lo, c in zip(
                *(columns(df, k) for k in ("open_time_utc", "open", "high", "low", "close")),
                strict=True,
            )
        ]
    r = run_perps_backtest(params, bars, fast, slow, allow_shorts=not long_only)
    typer.echo(
        json.dumps(
            {
                "disclaimer": "Simulated results on historical data. Not a forecast. "
                "Profitability is not guaranteed or implied.",
                "start_equity_usd": str(r.start_equity_usd),
                "end_equity_usd": str(r.end_equity_usd),
                "max_drawdown_pct": str(r.max_drawdown_pct),
                "trades": r.trades,
                "liquidations": r.liquidations,
                "fees_paid_usd": str(r.fees_paid_usd),
                "rejections": r.rejections,
            },
            indent=2,
        )
    )
