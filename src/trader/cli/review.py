"""``trader review``: the AI review assistant for the paper accounts (ADR-039).

It reads saved state, event logs, settings and public candles, asks role-based reviewers for
a report, and saves it under ``data/reports/``. It cannot edit settings or place orders; the
owner decides every change.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer

from trader.common.paths import configs_root, data_root
from trader.perps.review_facts import ACCOUNTS, account_files, bad_days, build_facts, read_events

from .common import EXIT_BLOCKED, EXIT_INVALID

app = typer.Typer(
    help="AI review assistant for the paper perps accounts (ADR-039).", no_args_is_help=True
)
ACCOUNT_HELP = f"Paper account: {' or '.join(ACCOUNTS)}."


def _report_paths(account: str, day: str) -> tuple[Path, Path]:
    base = data_root() / "reports" / f"review-{account}-{day}"
    return base.with_suffix(".md"), base.with_suffix(".json")


def _client_or_exit() -> Any:
    """An Anthropic client, or exit 3 when no key is configured on this machine."""
    from trader.perps.review_agents import KEY_ENV

    if not os.environ.get(KEY_ENV):
        typer.echo(
            f"REVIEW_ASSISTANT_BLOCKED: {KEY_ENV} is not set. Add it to .env on the server "
            "(never to the repository or chat), then restart the service.",
            err=True,
        )
        raise typer.Exit(EXIT_BLOCKED)
    import anthropic

    return anthropic.Anthropic()


def review_once(account: str, day: str | None, client: Any) -> tuple[str, Path]:
    """
    Build the facts, run every role, save the report; return its headline and path.

    Args:
        account (str): Account name.
        day (str | None): UTC day, or None for the latest bad day (else today).
        client (Any): Anthropic client.

    Returns:
        tuple[str, Path]: Headline and the Markdown report's path.
    """
    from trader.perps.review_agents import load_assistant_settings, run_review
    from trader.ui.data import kraken_public_ohlc

    facts = build_facts(
        account, day, data_root(), configs_root(), kraken_public_ohlc, datetime.now(UTC)
    )
    rv = run_review(facts, client, load_assistant_settings(configs_root()), configs_root())
    md, js = _report_paths(account, rv.day)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(rv.markdown, encoding="utf-8")
    payload = {
        "facts": facts,
        "notes": rv.notes,
        "proposals": rv.proposals,
        "headline": rv.headline,
    }
    js.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return rv.headline, md


@app.command("run")
def run(
    account: str = typer.Option("main", "--account", help=ACCOUNT_HELP),
    day: str | None = typer.Option(
        None, "--day", help="UTC day YYYY-MM-DD (default: latest bad day, else today)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the fact pack only; no AI request, no cost."
    ),
) -> None:
    """Review one day of a paper account and save the report. Exit 3 without an API key."""
    from trader.ui.data import kraken_public_ohlc

    if account not in ACCOUNTS:
        typer.echo(f"unknown account {account!r}; choose one of {sorted(ACCOUNTS)}", err=True)
        raise typer.Exit(EXIT_INVALID)
    if dry_run:
        try:
            facts = build_facts(
                account, day, data_root(), configs_root(), kraken_public_ohlc, datetime.now(UTC)
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(EXIT_INVALID) from None
        typer.echo(json.dumps(facts, indent=1, sort_keys=True, default=str))
        return
    client = _client_or_exit()
    try:
        headline, md = review_once(account, day, client)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INVALID) from None
    typer.echo(f"{headline}\nreport: {md}")


@app.command("show")
def show(
    account: str = typer.Option("main", "--account", help=ACCOUNT_HELP),
    day: str | None = typer.Option(
        None, "--day", help="UTC day YYYY-MM-DD (default: the newest report)."
    ),
) -> None:
    """Print a saved review report."""
    folder = data_root() / "reports"
    if day is None:
        found = sorted(folder.glob(f"review-{account}-*.md")) if folder.exists() else []
        if not found:
            typer.echo(f"no review reports for the {account} account yet")
            return
        md = found[-1]
    else:
        md = _report_paths(account, day)[0]
        if not md.exists():
            typer.echo(f"no review report for {account} on {day}")
            return
    typer.echo(md.read_text(encoding="utf-8"))


def due_days(account: str, done: set[str], today: str) -> list[str]:
    """
    Bad days of an account that still need a review (only today's and yesterday's).

    Args:
        account (str): Account name.
        done (set[str]): ``"<account>/<day>"`` already reviewed or attempted.
        today (str): Today, YYYY-MM-DD (UTC).

    Returns:
        list[str]: Days to review, oldest first.
    """
    yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
    days = bad_days(read_events(account_files(data_root(), account)[1]))
    return [d for d in days if d >= yesterday and f"{account}/{d}" not in done]


@app.command("watch")
def watch() -> None:
    """Review every new bad day of the configured accounts; alert when a report is ready."""
    from trader.perps.review_agents import load_assistant_settings
    from trader.session.alerts import Alerter

    settings = load_assistant_settings(configs_root())
    client = _client_or_exit()
    alerter = Alerter.from_env("[review]")
    cursor = data_root() / "state" / "review-assistant.json"
    done: set[str] = set(json.loads(cursor.read_text())["done"]) if cursor.exists() else set()
    typer.echo(f"review assistant watching {settings.accounts} for bad days")
    while settings.review_on_bad_day:
        today = datetime.now(UTC).date().isoformat()
        for account in settings.accounts:
            for day in due_days(account, done, today):
                done.add(f"{account}/{day}")
                try:
                    headline, _ = review_once(account, day, client)
                    alerter.send(
                        f"{account} {day}: {headline}. Read it: docker compose run --rm cli "
                        f"review show --account {account} --day {day}"
                    )
                except Exception as exc:  # noqa: BLE001 - one failed review must not stop the watcher
                    alerter.send(f"{account} {day}: review failed ({type(exc).__name__}: {exc})")
                cursor.parent.mkdir(parents=True, exist_ok=True)
                cursor.write_text(json.dumps({"done": sorted(done)}), encoding="utf-8")
        time.sleep(60)
