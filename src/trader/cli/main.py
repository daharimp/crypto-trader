"""``trader`` command-line entry point (D-40: CLI and core engine first)."""

from __future__ import annotations

import typer
from dotenv import load_dotenv

from trader import SAFETY_STATEMENT, __version__

from . import backtest, data, journal, killswitch, live, perps, profile, report, session, ui

load_dotenv()  # No secrets are required for M1; this only reads optional TRADER_* settings.

app = typer.Typer(
    help="AI-assisted crypto paper-trading research system. " + SAFETY_STATEMENT,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(profile.app, name="profile")
app.add_typer(data.app, name="data")
app.add_typer(backtest.app, name="backtest")
app.add_typer(report.app, name="report")
app.add_typer(journal.app, name="journal")
app.add_typer(killswitch.app, name="killswitch")
app.add_typer(session.app, name="session")
app.add_typer(live.app, name="live")
app.add_typer(perps.app, name="perps")
app.add_typer(ui.app, name="ui")


@app.command("version")
def version() -> None:
    """Print the package version and the safety statement."""
    typer.echo(f"ai-crypto-trader {__version__}")
    typer.echo(SAFETY_STATEMENT)


if __name__ == "__main__":  # pragma: no cover
    app()
