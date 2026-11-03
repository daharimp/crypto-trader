"""``trader profile build`` (terminal interview) and ``trader profile questions`` (ADR-024)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from trader.common.paths import configs_root as default_configs_root
from trader.profiles.builder import (
    BuildError,
    build,
    check_answer,
    registry_coins,
    runnable_strategies,
)
from trader.profiles.questions import HEADER_QUESTIONS, Question, bank_json, questions_for

Asker = Callable[[str], str]


def _show(q: Question, options: list[Any], echo: Callable[[str], None]) -> None:
    """Print one question with numbered options, pros/cons, and the custom range."""
    echo("")
    echo(f"[{q.section}] {q.prompt}" + (f"  ({q.ref})" if q.ref else ""))
    if q.why:
        echo(f"    {q.why}")
    for i, o in enumerate(options, start=1):
        rec = "  <- recommended" if o.recommended else ""
        note = "; ".join(x for x in (o.pros and f"+ {o.pros}", o.cons and f"- {o.cons}") if x)
        echo(f"  {i}) {o.label}{rec}" + (f"    {note}" if note else ""))
    if q.allows_custom:
        echo(f"  or type your own value between {q.custom_min:g} and {q.custom_max:g}")


def _parse(q: Question, options: list[Any], text: str) -> Any:
    """Map typed text to an answer value (option number, custom value, list, or text)."""
    text = text.strip()
    if q.kind == "text":
        return text
    rec = next((o for o in options if o.recommended), None)
    if not text and rec is not None:
        return rec.value
    if q.kind == "multi":
        picks = [p.strip() for p in text.split(",") if p.strip()]
        return [options[int(p) - 1].value if p.isdigit() else p.upper() for p in picks]
    # Reason: an option's own value or key wins over its position, so typing "2" on a
    # question whose options are 2 / 3 / 5 means the value 2, not the second option.
    for o in options:
        if text in (o.key, str(o.value)):
            return o.value
    if text.isdigit() and 1 <= int(text) <= len(options) and not q.allows_custom:
        return options[int(text) - 1].value
    if text.startswith("#") and text[1:].isdigit():
        return options[int(text[1:]) - 1].value
    if q.kind == "range":
        if "-" in text:
            return [x.strip() for x in text.split("-", 1)]
        return options[int(text) - 1].value
    return text


def ask(
    q: Question, asker: Asker, echo: Callable[[str], None], options: list[Any] | None = None
) -> Any:
    """
    Ask one question until the answer passes the bank's checks.

    Args:
        q (Question): Question.
        asker (Asker): Reads one line (``input`` or a test stub).
        echo (Callable[[str], None]): Prints one line.
        options (list[Any] | None): Options to show (defaults to the question's).

    Returns:
        Any: Validated answer.
    """
    opts = list(options if options is not None else q.options)
    _show(q, opts, echo)
    hint = "Enter = recommended" if any(o.recommended for o in opts) else ""
    if q.allows_custom and opts:
        hint += ("; " if hint else "") + "#N picks option N"
    while True:
        text = asker(f"> {('(' + hint + ') ') if hint else ''}")
        try:
            return check_answer(q, _parse(q, opts, text))
        except (BuildError, ValueError, IndexError, TypeError) as exc:
            echo(f"  not accepted: {exc}")


def interview(root: Path, asker: Asker, echo: Callable[[str], None]) -> dict[str, Any]:
    """
    Run the full interview.

    Args:
        root (Path): Configuration directory.
        asker (Asker): Line reader.
        echo (Callable[[str], None]): Line printer.

    Returns:
        dict[str, Any]: Answers keyed by question ID.
    """
    answers: dict[str, Any] = {q.id: ask(q, asker, echo) for q in HEADER_QUESTIONS}
    strategies = runnable_strategies(root)
    for q in questions_for(answers["preset"], strategies, registry_coins(root)):
        opts = None
        if q.id == "strategy_id":
            tf = answers["decision_timeframe"]
            opts = [
                o
                for o in q.options
                if tf in next(s["timeframes"] for s in strategies if s["id"] == o.value)
            ]
        if q.id == "intraday_limits" and int(answers.get("intraday_cap_pct", 0)) == 0:
            answers[q.id] = "B"  # unused while the slice is off
            continue
        answers[q.id] = ask(q, asker, echo, opts)
    return answers


def register(app: typer.Typer) -> None:
    """
    Add ``build`` and ``questions`` to the ``profile`` command group.

    Args:
        app (typer.Typer): The ``trader profile`` app.
    """

    @app.command("build")
    def build_cmd(
        answers: Path | None = typer.Option(None, "--answers", help="Answers JSON (web form)."),
        update: bool = typer.Option(False, "--update", help="Write a new version of a profile."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Check only; write nothing."),
        docs_dir: Path = typer.Option(Path("docs/profiles"), "--docs-dir"),
    ) -> None:
        """Interview (or read --answers), then write the risk profile, trading profile, spec."""
        root = default_configs_root()
        if answers is not None:
            try:
                raw = json.loads(answers.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                typer.echo(f"cannot read answers: {exc}", err=True)
                raise typer.Exit(2) from None
            raw = raw.get("answers", raw)
        else:
            typer.echo("Profile builder: every value you choose is recorded as your approval.")
            typer.echo("Results are not guaranteed; real money can be lost.")
            raw = interview(root, input, typer.echo)
        try:
            res = build(raw, root, docs_dir, update=update, dry_run=dry_run)
        except BuildError as exc:
            typer.echo(f"not built: {exc}", err=True)
            raise typer.Exit(2) from None
        for e in res.errors:
            typer.echo(f"  - {e}", err=True)
        if res.errors:
            typer.echo("not written: fix the answers above and run again", err=True)
            raise typer.Exit(2)
        if dry_run:
            typer.echo(f"dry run OK (exit {res.exit_code}); nothing written")
        else:
            typer.echo(f"wrote {res.risk_path}\nwrote {res.profile_path}\nwrote {res.spec_path}")
        raise typer.Exit(res.exit_code)

    @app.command("questions")
    def questions_cmd(
        out: Path | None = typer.Option(None, "--out", help="Write the bank JSON here."),
    ) -> None:
        """Export the question bank as JSON (the web form reads it)."""
        root = default_configs_root()
        text = json.dumps(
            bank_json(runnable_strategies(root), registry_coins(root)), indent=1, default=str
        )
        if out:
            out.write_text(text)
            typer.echo(f"wrote {out}")
        else:
            typer.echo(text)
