"""Shared CLI helpers and exit codes (§7.14)."""

from __future__ import annotations

from datetime import datetime

import typer

from trader.common.clock import NaiveTimestampError, parse_utc

EXIT_OK, EXIT_INTERNAL, EXIT_INVALID, EXIT_BLOCKED, EXIT_INTEGRITY = 0, 1, 2, 3, 4


def utc_option(value: str | None) -> datetime | None:
    """
    Parse an ISO timestamp option that must carry a timezone.

    Args:
        value (str | None): Text such as ``2024-01-01T00:00:00Z``.

    Returns:
        datetime | None: UTC datetime.

    Raises:
        typer.Exit: Code 2 on naive or invalid timestamps.
    """
    if value is None:
        return None
    try:
        return parse_utc(value)
    except NaiveTimestampError:
        typer.echo("NAIVE_TIMESTAMP: timestamps must include a timezone (e.g. Z)", err=True)
        raise typer.Exit(EXIT_INVALID) from None
    except ValueError as exc:
        typer.echo(f"invalid timestamp {value!r}: {exc}", err=True)
        raise typer.Exit(EXIT_INVALID) from None
