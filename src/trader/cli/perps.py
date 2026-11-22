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

# Separate paper accounts (ADR-038): name -> (config file under configs/perps/, file stem
# for data/state/<stem>.json and data/logs/<stem>-events.jsonl, alert prefix).
ACCOUNTS = {
    "main": ("jupiter.yaml", "perps-paper", "[perps paper]"),
    "degen": ("jupiter-degen.yaml", "perps-degen", "[perps degen]"),
}
ACCOUNT_HELP = "Paper account: main (the running one) or degen (ADR-038)."


def account_paths(root: Path, account: str) -> tuple[Path, Path]:
    """
    State file and event log of a paper perps account.

    Args:
        root (Path): Data directory.
        account (str): Account name from ``ACCOUNTS``.

    Returns:
        tuple[Path, Path]: ``(state, events)``.
    """
    stem = ACCOUNTS[account][1]
    return root / "state" / f"{stem}.json", root / "logs" / f"{stem}-events.jsonl"


def account_equity_path(root: Path, account: str) -> Path:
    """Per-bar equity log of a paper perps account (ADR-041): ``logs/<stem>-equity.jsonl``."""
    return root / "logs" / f"{ACCOUNTS[account][1]}-equity.jsonl"


def account_archive_dir(root: Path, account: str) -> Path:
    """Folder of an account's archived runs (ADR-041): ``archive/perps/<stem>``."""
    return root / "archive" / "perps" / ACCOUNTS[account][1]


def _account_or_exit(account: str) -> str:
    if account not in ACCOUNTS:
        typer.echo(f"unknown account {account!r}; choose one of {sorted(ACCOUNTS)}", err=True)
        raise typer.Exit(EXIT_INVALID)
    return account


def _params_or_exit(account: str = "main") -> PerpsParams:
    """Load an account's perps parameters or exit 3 (unresolved) / 2 (invalid)."""
    try:
        return load_perps_params(file_name=ACCOUNTS[_account_or_exit(account)][0])
    except PerpsConfigUnresolvedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_BLOCKED) from None
    except ValueError as exc:
        typer.echo(f"invalid perps config: {exc}", err=True)
        raise typer.Exit(EXIT_INVALID) from None


@app.command("validate")
def validate(account: str = typer.Option("main", "--account", help=ACCOUNT_HELP)) -> None:
    """Check an account's perps config. Exit 3 lists every unresolved value."""
    params = _params_or_exit(account)
    stop = params.stop_loss_pct_of_collateral
    tps = params.take_profits
    ladder = (
        "off"
        if tps is None
        else "/".join(f"{r}R" for r, _ in tps) + " closing " + "/".join(f"{p}%" for _, p in tps)
    )
    typer.echo(
        f"perps config {ACCOUNTS[account][0]} v{params.version}: all values approved "
        f"(paper only); {params.max_collateral_per_position_pct}% collateral per position, "
        f"buffer {params.liquidation_buffer_daily_moves or 'off'} daily moves, "
        f"stop {f'{stop}% of collateral' if stop else 'off'}, "
        f"daily loss limit {params.daily_loss_limit_pct}%, take-profit ladder {ladder}"
    )


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


@paper_app.command("run")
def paper_run(
    once: bool = typer.Option(False, "--once", help="Process due bars once, then exit."),
    timeframe: str = typer.Option(
        "4h",
        "--timeframe",
        help="How often to check: 4h, or 1h (the trend still comes from 4h candles).",
    ),
    signal_name: str = typer.Option(
        DEFAULT_SIGNAL,
        "--signal",
        help="tsmom_30d (1-month trend), sma_stance_20_50, or consensus_sma_tsmom (both agree).",
    ),
    account: str = typer.Option("main", "--account", help=ACCOUNT_HELP),
) -> None:
    """Run the paper perps session until stopped. Paper only: it cannot place a real order.

    Exit 3 if any perps value is unapproved; exit 2 if the saved state does not match.
    """
    from trader.perps.session import PerpsSession, SessionStateError
    from trader.perps.signals import make_signal
    from trader.risk.controls import PersistedKillSwitch
    from trader.session.alerts import Alerter
    from trader.ui.data import kraken_public_ohlc

    params = _params_or_exit(account)
    alerter = Alerter.from_env(ACCOUNTS[account][2])
    state_path, events_path = account_paths(data_root(), account)
    try:
        session = PerpsSession(
            params,
            kraken_public_ohlc,
            state_path,
            events_path,
            notify=alerter.send,
            halted=PersistedKillSwitch().is_engaged,
            # Reason: an hourly sweep reads its 30-day trend from 4h candles (ADR-040).
            signal=make_signal(signal_name, 6),
            signal_name=signal_name,
            timeframe=timeframe,
            trend_timeframe="4h" if timeframe == "1h" else None,
            equity_path=account_equity_path(data_root(), account),
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
            except SessionStateError as exc:
                # Reason: the run was archived under this process (ADR-041); exiting lets the
                # container restart into a fresh run instead of resurrecting the old one.
                alerter.send(f"session stopped: {exc}")
                typer.echo(f"perps session stopped: {exc}", err=True)
                raise typer.Exit(EXIT_INVALID) from None
            except Exception as exc:  # noqa: BLE001 - keep the loop alive; retry next tick
                # Reason: alert once per outage, not every minute.
                if not failing:
                    alerter.send(f"cycle failed, will retry: {type(exc).__name__}: {exc}")
                failing = True
        time.sleep(60)
    typer.echo("perps paper session stopped")


@paper_app.command("status")
def paper_status(account: str = typer.Option("main", "--account", help=ACCOUNT_HELP)) -> None:
    """Show a paper perps session: equity, positions, and progress."""
    from trader.perps.session import read_status

    s = read_status(account_paths(data_root(), _account_or_exit(account))[0])
    # Reason: the main account's wording is unchanged; only other accounts are named.
    label = "" if account == "main" else f" {account}"
    if s is None:
        typer.echo(f"no perps paper{label} session has run on this machine yet")
        return
    start, equity = Decimal(s["start_equity_usd"]), Decimal(s["equity_usd"])
    typer.echo(
        f"perps paper{label} ({s['signal']}, {s['timeframe']}): equity ${equity:.2f} "
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


def _money(x: object) -> str:
    return "?" if x is None else f"${Decimal(str(x)):,.2f}"


@paper_app.command("reset")
def paper_reset(
    reason: str = typer.Option(..., "--reason", help="Why this run ends (kept in its summary)."),
    account: str = typer.Option("main", "--account", help=ACCOUNT_HELP),
) -> None:
    """Archive the current run and start the next one fresh. Nothing is deleted (ADR-041).

    Stop the account first (`docker compose stop perps`), then start it again afterwards.
    Exit 2 if there is no saved run or the archive folder already exists.
    """
    from trader.perps.runs import RunArchiveError, archive_run

    root = data_root()
    state_path, events_path = account_paths(root, _account_or_exit(account))
    try:
        run_dir = archive_run(
            state_path,
            events_path,
            account_equity_path(root, account),
            account_archive_dir(root, account),
            reason,
            datetime.now(UTC),
        )
    except RunArchiveError as exc:
        typer.echo(f"not reset: {exc}", err=True)
        raise typer.Exit(EXIT_INVALID) from None
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    typer.echo(
        f"archived {account} run {s['run']}: {_money(s['start_equity_usd'])} -> "
        f"{_money(s['final_equity_usd'])} ({s['pnl_pct']}%), peak {_money(s['peak_equity_usd'])}, "
        f"largest drop {s['max_drawdown_pct']}%"
    )
    typer.echo(f"saved in {run_dir}; the next start begins a fresh run.")


@paper_app.command("runs")
def paper_runs(account: str = typer.Option("main", "--account", help=ACCOUNT_HELP)) -> None:
    """List an account's past runs, including state files moved aside before ADR-041."""
    from trader.perps.runs import list_runs

    root = data_root()
    runs = list_runs(
        account_archive_dir(root, _account_or_exit(account)),
        root / "state",
        ACCOUNTS[account][1],
    )
    if not runs:
        typer.echo(f"no archived {account} runs yet")
        return
    for r in runs:
        if "error" in r:
            typer.echo(f"  {r['run']}: {r['error']}")
            continue
        trades = (
            f", {r['trades_closed']} trades ({r['stops']} stopped, {r['liquidations']} liquidated)"
            if "trades_closed" in r
            else ""
        )
        typer.echo(
            f"  {r['run']}{' (moved by hand, no equity curve)' if r.get('legacy') else ''}: "
            f"{r.get('signal')} {r.get('timeframe')}, {_money(r.get('start_equity_usd'))} -> "
            f"{_money(r.get('final_equity_usd'))} ({r.get('pnl_pct')}%), peak "
            f"{_money(r.get('peak_equity_usd'))}, largest drop {r.get('max_drawdown_pct')}%"
            f"{trades}" + (f"; reason: {r['reason']}" if r.get("reason") else "")
        )
    typer.echo("Simulated money. Results are not a forecast; profit is not guaranteed.")
