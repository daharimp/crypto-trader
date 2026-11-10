"""``trader ui serve``: read-only phone dashboard (ADR-025)."""

from __future__ import annotations

import os
from typing import Any

import typer

from trader.common.paths import data_root
from trader.perps.params import load_perps_file, load_perps_params
from trader.perps.prices import fetch_prices
from trader.risk.controls import PersistedKillSwitch
from trader.ui.data import kraken_public_ohlc, status_snapshot
from trader.ui.server import Sources, serve

app = typer.Typer(help="Read-only dashboard (ADR-025).", no_args_is_help=True)


def _kill_switch() -> dict[str, Any] | None:
    s = PersistedKillSwitch().state()
    if s is None:
        return None
    return {k: str(v) for k, v in s.model_dump(mode="json").items()}


@app.command("serve")
def serve_cmd(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Bind address; keep localhost unless behind a private network"
    ),
    port: int = typer.Option(8787, "--port"),
) -> None:
    """Serve the dashboard. GET only; it cannot trade or change settings."""

    def prices() -> dict[str, Any]:
        markets: dict[str, str] = {m.market: m.price_mint for m in load_perps_file().markets}
        return {k: float(v) for k, v in fetch_prices(markets).items()}

    src = Sources(
        lambda: status_snapshot(data_root(), _kill_switch()),
        kraken_public_ohlc,
        load_perps_params,
        prices,
    )
    # Reason: in Docker the server binds 0.0.0.0 inside the container, while compose
    # publishes it on the host's 127.0.0.1 only (docker-compose.yml, ADR-025).
    in_container = os.environ.get("TRADER_IN_CONTAINER") == "1"
    if host not in ("127.0.0.1", "localhost", "::1") and not in_container:
        typer.echo(
            "warning: serving beyond this machine; put it behind a VPN or SSH tunnel", err=True
        )
    httpd = serve(src, host, port)
    typer.echo(f"dashboard: http://{host}:{httpd.server_address[1]}/  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
