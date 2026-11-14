"""``trader perps validate|prices|backtest|paper``: Jupiter Perps, paper only (ADR-025)."""

from __future__ import annotations

import json
import signal
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import typer

from trader.common.paths import data_root
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
from trader.perps.signals import DEFAULT_SIGNAL

from .common import EXIT_BLOCKED, EXIT_INVALID

app = typer.Typer(help="Jupiter Perps research, paper only (ADR-025).", no_args_is_help=True)


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


paper_app = typer.Typer(
    help="Forward paper perps session on live prices: long and short (ADR-031).",
    no_args_is_help=True,
)
app.add_typer(paper_app, name="paper")


def _paper_paths() -> tuple[Path, Path]:
    root = data_root()
    return root / "state" / "perps-paper.json", root / "logs" / "perps-paper-events.jsonl"


@paper_app.command("run")
def paper_run(
    once: bool = typer.Option(False, "--once", help="Process due bars once, then exit."),
    timeframe: str = typer.Option("4h", "--timeframe", help="Decision timeframe: 1h or 4h."),
    signal_name: str = typer.Option(
        DEFAULT_SIGNAL,
        "--signal",
        help="tsmom_30d (1-month trend), sma_stance_20_50, or consensus_sma_tsmom (both agree).",
    ),
) -> None:
    """Run the paper perps session until stopped. Paper only: it cannot place a real order.

    Exit 3 if any perps value is unapproved; exit 2 if the saved state does not match.
    """
    from trader.perps.session import PerpsSession, SessionStateError
    from trader.perps.signals import make_signal
    from trader.risk.controls import PersistedKillSwitch
    from trader.session.alerts import Alerter
    from trader.ui.data import kraken_public_ohlc

    params = _params_or_exit()
    alerter = Alerter.from_env("[perps paper]")
    state_path, events_path = _paper_paths()
    try:
        session = PerpsSession(
            params,
            kraken_public_ohlc,
            state_path,
            events_path,
            notify=alerter.send,
            halted=PersistedKillSwitch().is_engaged,
            signal=make_signal(signal_name, {"1h": 24, "4h": 6}.get(timeframe, 6)),
            signal_name=signal_name,
            timeframe=timeframe,
        )
    except (SessionStateError, ValueError) as exc:
        typer.echo(f"perps session not started: {exc}", err=True)
        raise typer.Exit(EXIT_INVALID) from None
    resumed = session.acct is not None
    typer.echo(f"perps paper session {'resumed' if resumed else 'starting'}; state: {state_path}")
    if once:
        events = session.cycle(datetime.now(UTC))
        typer.echo(json.dumps({"events": len(events), **session.meta}, indent=1))
        return
    stop = {"flag": False}

    def _stop(signum: int, frame: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    alerter.send(f"session {'resumed' if resumed else 'started'} (simulated money)")
    failing = False
    while not stop["flag"]:
        now = datetime.now(UTC)
        if session.due(now):
            try:
                session.cycle(now)
                if failing:
                    alerter.send("price data is back; session continuing")
                failing = False
            except Exception as exc:  # noqa: BLE001 - keep the loop alive; retry next tick
                # Reason: alert once per outage, not every minute.
                if not failing:
                    alerter.send(f"cycle failed, will retry: {type(exc).__name__}: {exc}")
                failing = True
        time.sleep(60)
    typer.echo("perps paper session stopped")


@paper_app.command("status")
def paper_status() -> None:
    """Show the paper perps session: equity, positions, and progress."""
    from trader.perps.session import read_status

    s = read_status(_paper_paths()[0])
    if s is None:
        typer.echo("no perps paper session has run on this machine yet")
        return
    start, equity = Decimal(s["start_equity_usd"]), Decimal(s["equity_usd"])
    typer.echo(
        f"perps paper ({s['signal']}, {s['timeframe']}): equity ${equity:.2f} "
        f"({equity - start:+.2f} from ${start:.2f}), largest drop {s['max_drawdown_pct']}%, "
        f"fees ${Decimal(s['fees_paid_usd']):.2f}, {s['cycles']} bars processed, "
        f"last bar {s['last_bar']}"
    )
    for p in s["positions"]:
        typer.echo(
            f"  {p['side']} {p['market']}: ${p['size_usd']} position on "
            f"${p['collateral_usd']} collateral, entry {p['entry_price']}"
        )
    if not s["positions"]:
        typer.echo("  no open positions")
    typer.echo("Simulated money. Results are not a forecast; profit is not guaranteed.")
