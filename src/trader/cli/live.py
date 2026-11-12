"""``trader live preflight``: check Kraken keys and order shapes without trading."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import typer

from trader.domain.enums import Environment

app = typer.Typer(help="Live-trading tools (ADR-023).", no_args_is_help=True)


@app.command("preflight")
def preflight(profile: Path = typer.Option(..., "--profile")) -> None:
    """Validate keys, permissions, balances, and order shapes. Places NO orders."""
    from trader.execution.adapters.kraken_live import KrakenLiveAdapter
    from trader.profiles.compiler import compile_bundle
    from trader.session.config import SessionError, api_keys_from_env
    from trader.session.market_data import KrakenMarketData, kraken_symbols, make_kraken_client
    from trader.session.preflight import run_preflight
    from trader.universe.registry import Registry

    b = compile_bundle(profile, Environment.LIVE, assume_activated=True)
    if b.registry is None or b.live is None:
        typer.echo(
            "live authorization or registry missing: " + "; ".join(b.compiled.errors), err=True
        )
        raise typer.Exit(2)
    try:
        key, secret = api_keys_from_env(b.live.api_key_env["key"], b.live.api_key_env["secret"])
    except SessionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    symbols = kraken_symbols(Registry(b.registry))
    client = make_kraken_client(key, secret)
    cap = b.live.max_capital_usd.value
    adapter = KrakenLiveAdapter(
        client, symbols, Decimal(str(cap)) if cap != "TBD" else Decimal(1), Decimal("0.40")
    )
    checks = run_preflight(
        adapter, KrakenMarketData(make_kraken_client(), symbols), datetime.now(UTC)
    )
    for c in checks:
        typer.echo(f"[{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    typer.echo(
        "gates: "
        + ("; ".join(b.compiled.errors) or "no errors")
        + " | blockers: "
        + (", ".join(sorted({x.ref for x in b.compiled.blockers})) or "none")
    )
    raise typer.Exit(0 if all(c.ok for c in checks) else 2)
