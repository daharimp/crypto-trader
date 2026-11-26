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

from trader.assistant.trades import ALL_ACCOUNTS, SPOT, closed_trades
from trader.common.paths import configs_root, data_root
from trader.perps.review_facts import ACCOUNTS, account_files, bad_days, build_facts, read_events
from trader.perps.session import read_status

from .common import EXIT_BLOCKED, EXIT_INVALID

app = typer.Typer(
    help="AI review assistant for every paper account (ADR-039, ADR-045).", no_args_is_help=True
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
    daily: bool = typer.Option(False, "--daily", help="Show a daily summary instead."),
    trades: bool = typer.Option(False, "--trades", help="Show the account's newest trade review."),
) -> None:
    """Print a saved review report (bad-day review, daily summary, or trade review)."""
    folder = data_root() / "reports"
    if daily or trades:
        pattern = f"daily-{day or '*'}.md" if daily else f"trades/{account}/*.md"
        found = sorted(folder.glob(pattern)) if folder.exists() else []
        if not found:
            typer.echo("no matching reports yet")
            return
        typer.echo(found[-1].read_text(encoding="utf-8"))
        return
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


def _timeframe(account: str) -> tuple[str, str | None]:
    """Candle timeframe and signal name an account trades on (spot: 4h, unknown signal)."""
    if account == SPOT:
        return "4h", None
    st = read_status(account_files(data_root(), account)[0]) or {}
    return str(st.get("timeframe", "4h")), st.get("signal")


def enrich_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Measured facts for one trade (no AI request), for the end-of-day batch review."""
    from trader.assistant.trade_review import build_trade_facts
    from trader.ui.data import kraken_public_ohlc

    tf, rule = _timeframe(trade["account"])
    return build_trade_facts(trade, configs_root(), kraken_public_ohlc, tf, rule)


def review_trade(trade: dict[str, Any], client: Any, settings: Any) -> tuple[str, Path]:
    """
    Analyze one closed trade and save its report; return a one-line alert and the path.

    Args:
        trade (dict[str, Any]): From ``trades.closed_trades``.
        client (Any): Anthropic client.
        settings (Any): Assistant settings.

    Returns:
        tuple[str, Path]: Alert line and the Markdown report's path.
    """
    from trader.assistant.trade_review import analyze_trade, build_trade_facts, save_trade_report
    from trader.ui.data import kraken_public_ohlc

    tf, rule = _timeframe(trade["account"])
    facts = build_trade_facts(trade, configs_root(), kraken_public_ohlc, tf, rule)
    a = analyze_trade(facts, client, settings)
    md = save_trade_report(data_root() / "reports", facts, a)
    pnl = trade.get("net_pnl_usd")
    money = "" if pnl is None else f" ${pnl:,.2f}"
    head = f"{a.headline} ({a.grade})" if a else "analysis unavailable"
    return f"{trade['account']} {trade['side']} {trade['market']} closed{money}: {head}", md


@app.command("trade")
def trade_cmd(
    account: str = typer.Option("main", "--account", help=f"One of {', '.join(ALL_ACCOUNTS)}."),
    last: int = typer.Option(1, "--last", min=1, max=20, help="How many recent trades."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the trades only; no AI cost."),
) -> None:
    """Analyze recent closed trade(s) now, one AI request each (the daily batch is cheaper)."""
    if account not in ALL_ACCOUNTS:
        typer.echo(f"unknown account {account!r}; choose one of {list(ALL_ACCOUNTS)}", err=True)
        raise typer.Exit(EXIT_INVALID)
    picked = closed_trades(data_root(), account)[-last:]
    if not picked:
        typer.echo(f"no closed trades for the {account} account yet")
        return
    if dry_run:
        typer.echo(json.dumps(picked, indent=1, sort_keys=True, default=str))
        return
    from trader.perps.review_agents import load_assistant_settings

    client, settings = _client_or_exit(), load_assistant_settings(configs_root())
    for t in picked:
        line, md = review_trade(t, client, settings)
        typer.echo(f"{line}\nreport: {md}")


@app.command("daily")
def daily_cmd(
    day: str | None = typer.Option(None, "--day", help="UTC day YYYY-MM-DD (default: yesterday)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the facts only; no AI cost."),
) -> None:
    """Write the daily summary of every account in configs/assistant.yaml."""
    from trader.assistant.daily import daily_facts, write_daily
    from trader.perps.review_agents import load_assistant_settings

    settings = load_assistant_settings(configs_root())
    accounts: list[str] = [*settings.report_accounts] or [*ALL_ACCOUNTS]
    day = day or (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    if dry_run:
        typer.echo(json.dumps(daily_facts(data_root(), accounts, day), indent=1, default=str))
        return
    headline, md = write_daily(
        data_root(), accounts, day, _client_or_exit(), settings, enrich_trade
    )
    typer.echo(f"{headline}\nreport: {md}")


def _load_cursor(path: Path) -> dict[str, Any]:
    d: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
    for k in ("done", "daily_done"):
        d.setdefault(k, [])
    d.setdefault("drawdown_seen", {})
    d.setdefault("free_done", [])
    d.setdefault("free_calls", {})
    return d


def watch_once(
    cur: dict[str, Any],
    client: Any,
    settings: Any,
    send: Any,
    now: datetime,
    free: Any = None,
) -> None:
    """
    One pass of the watcher: bad days, the end-of-day summary with every trade, drawdowns.

    Args:
        cur (dict[str, Any]): Cursor (updated in place; the caller saves it).
        client (Any): Anthropic client (None when ``server_ai_reviews`` is off).
        settings (Any): Assistant settings.
        send (Any): Alert function, text -> None.
        now (datetime): Current time (UTC).
        free (Any): Free-model trade reviewer (ADR-049), or None when off or no key.
    """
    from trader.assistant.daily import drawdown_alerts, write_daily

    today = now.date().isoformat()
    done = set(cur["done"])
    if settings.review_on_bad_day and settings.server_ai_reviews:
        for account in settings.accounts:
            for day in due_days(account, done, today):
                done.add(f"{account}/{day}")
                cur["done"] = sorted(done)
                try:
                    headline, _ = review_once(account, day, client)
                    send(
                        f"{account} {day}: {headline}. Read it: docker compose run --rm cli "
                        f"review show --account {account} --day {day}"
                    )
                except Exception as exc:  # noqa: BLE001 - one failed review must not stop the watcher
                    send(f"{account} {day}: review failed ({type(exc).__name__}: {exc})")
    accounts = list(settings.report_accounts)
    yesterday = (now - timedelta(days=1)).date().isoformat()
    # Reason: wait 10 minutes past midnight UTC so 4h and 1h sessions finish the day's last bar.
    if (
        settings.daily_summary
        and settings.server_ai_reviews
        and now.hour * 60 + now.minute >= 10
        and yesterday not in cur["daily_done"]
    ):
        cur["daily_done"] = sorted({*cur["daily_done"], yesterday})[-60:]
        try:
            headline, _ = write_daily(
                data_root(),
                accounts or list(ALL_ACCOUNTS),
                yesterday,
                client,
                settings,
                enrich_trade,
            )
            send(
                f"daily {yesterday}: {headline}. Read it: docker compose run --rm cli "
                "review show --daily"
            )
        except Exception as exc:  # noqa: BLE001 - a failed summary must not stop the watcher
            send(f"daily {yesterday}: summary failed ({type(exc).__name__}: {exc})")
    for line in drawdown_alerts(
        data_root(), accounts, settings.drawdown_alert_pct, cur["drawdown_seen"]
    ):
        send(line)
    if free is not None:
        from trader.assistant.free_review import run_pass
        from trader.ui.data import kraken_public_ohlc

        run_pass(
            cur,
            free,
            data_root(),
            accounts or list(ALL_ACCOUNTS),
            now,
            enrich_trade,
            send,
            kraken_public_ohlc,
        )


@app.command("watch")
def watch() -> None:
    """Review bad days, each day with its trades, and drawdowns; alert when ready (ADR-046)."""
    from trader.perps.review_agents import load_assistant_settings
    from trader.session.alerts import Alerter

    settings = load_assistant_settings(configs_root())
    # Reason: with server AI reviews off (ADR-048) only the code-only drawdown alerts run, so
    # no API key is needed.
    client = _client_or_exit() if settings.server_ai_reviews else None
    alerter = Alerter.from_env("[review]")
    path = data_root() / "state" / "review-assistant.json"
    cur = _load_cursor(path)
    if settings.server_ai_reviews:
        typer.echo(
            f"review assistant: bad days {settings.accounts}, daily+trades/drawdown "
            f"{settings.report_accounts}"
        )
    else:
        typer.echo(f"review assistant: drawdown alerts only {settings.report_accounts} (ADR-048)")
    from trader.assistant.free_review import KEY_ENV as FREE_KEY
    from trader.assistant.free_review import reviewer_from_env

    free_cfg = settings.free_trade_reviews
    free = reviewer_from_env(free_cfg)
    if free is not None:
        typer.echo(f"free per-trade reviews: on, models {free_cfg.models} (ADR-049)")
    elif free_cfg.enabled:
        typer.echo(f"free per-trade reviews: skipped until {FREE_KEY} is set in .env (ADR-049)")
    while True:
        watch_once(cur, client, settings, alerter.send, datetime.now(UTC), free)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cur, sort_keys=True), encoding="utf-8")
        time.sleep(60)
