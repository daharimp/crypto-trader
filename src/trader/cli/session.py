"""``trader session run|status|flatten|reset-breaker`` (forward paper and live, BL-027)."""

from __future__ import annotations

import json
import signal
from datetime import UTC, datetime
from pathlib import Path

import typer

from trader.common.opstore import OperationalStore
from trader.common.paths import data_root
from trader.domain.enums import Environment

app = typer.Typer(help="Run and control forward paper/live sessions.", no_args_is_help=True)


@app.command("run")
def run(
    profile: Path = typer.Option(..., "--profile"),
    environment: Environment = typer.Option(..., "--environment", "-e", help="paper or live"),
    strategy: str | None = typer.Option(
        None, "--strategy", help="Default: the profile's trading_spec, else sma_trend."
    ),
    timeframe: str | None = typer.Option(
        None, "--timeframe", help="Default: the profile's trading_spec, else 4h."
    ),
    once: bool = typer.Option(False, "--once", help="Process due cycles once, then exit."),
) -> None:
    """Run a session until stopped (SIGTERM/Ctrl-C). Exit 2/3 if a gate refuses to start."""
    from trader.session.config import SessionConfig, SessionError, session_defaults
    from trader.session.factory import kraken_adapter_factory
    from trader.session.market_data import (
        KrakenMarketData,
        MarketDataError,
        kraken_symbols,
        make_kraken_client,
    )
    from trader.session.runner import SessionRunner
    from trader.universe.registry import Registry

    try:
        from trader.profiles.compiler import compile_bundle

        b = compile_bundle(profile, environment)
        if b.registry is None:
            raise SessionError(2, "; ".join(b.compiled.errors))
        strategy, timeframe = session_defaults(b.profile, strategy, timeframe)
        data = KrakenMarketData(make_kraken_client(), kraken_symbols(Registry(b.registry)))
        runner = SessionRunner(
            SessionConfig(profile, environment, strategy, timeframe),
            data,
            adapter_factory=kraken_adapter_factory if environment == Environment.LIVE else None,
        )
        runner.start()
    except (SessionError, MarketDataError) as exc:
        typer.echo(f"session not started: {exc}", err=True)
        raise typer.Exit(getattr(exc, "exit_code", 2)) from None
    typer.echo(f"{environment.value} session started; state: {runner.path}")
    if once:
        runner.tick()
        runner.state.journal.close()
        typer.echo(json.dumps(runner.meta, indent=1, default=str))
        return
    stop = {"flag": False}

    def _stop(signum: int, frame: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    runner.run_forever(lambda: stop["flag"])
    typer.echo("session stopped")


@app.command("status")
def status() -> None:
    """Show every session's last cycle, equity, positions, and controls."""
    files = sorted((data_root() / "state").glob("session-*.json"))
    from trader.risk.controls import PersistedKillSwitch

    ks = PersistedKillSwitch().state()
    typer.echo(
        f"kill switch: {ks.state if ks else 'disengaged (initial)'}"
        + (f" ({ks.reason})" if ks else "")
    )
    if not files:
        typer.echo("no sessions yet")
        return
    for f in files:
        d = json.loads(f.read_text())
        m, led = d["meta"], d["ledger"]
        pos = {
            k: f"{p['quantity']} @ {p['avg_entry_price']} stop {p['stop_price']}"
            for k, p in led["positions"].items()
        }
        typer.echo(
            f"{f.stem}: last bar {m.get('last_t1')} (ran {m.get('last_cycle_wall_utc')}), "
            f"equity ${float(m.get('equity_usd', led['cash'])):.2f}, cash "
            f"${float(led['cash']):.2f}, positions {pos or 'none'}, breaker "
            f"{'OPEN' if d['controls']['breaker_open'] else 'closed'}, stale cycles "
            f"{m.get('stale_cycles', 0)}, closed trades {len(led['trades'])}"
        )


def _request(kind: str, reason: str) -> None:
    """
    Queue an owner request for the running session.

    Args:
        kind (str): Request kind.
        reason (str): Reason.

    Raises:
        typer.Exit: Code 2 on a blank reason.
    """
    if not reason.strip():
        typer.echo("a reason is required", err=True)
        raise typer.Exit(2)
    rid = OperationalStore().request(kind, reason, datetime.now(UTC))
    typer.echo(f"{kind} request #{rid} queued; the running session executes it within ~30 s")


@app.command("flatten")
def flatten(reason: str = typer.Option(..., "--reason")) -> None:
    """Owner command: sell all positions through the risk engine (works with the kill switch)."""
    _request("flatten", reason)


@app.command("reset-breaker")
def reset_breaker(reason: str = typer.Option(..., "--reason")) -> None:
    """Owner command: reset a tripped drawdown circuit breaker."""
    _request("reset_breaker", reason)
