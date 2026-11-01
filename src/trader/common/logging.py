"""JSON-lines logging with run and correlation context (§7.15)."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CTX: ContextVar[dict[str, str | None] | None] = ContextVar("trader_log_ctx", default=None)
_FIELDS = ("run_id", "cycle_id", "correlation_id", "event_type")


def set_log_context(**kwargs: str | None) -> None:
    """
    Merge values into the logging context (run_id, cycle_id, correlation_id, event_type).

    Args:
        **kwargs: Context fields to set.
    """
    ctx = dict(_CTX.get() or {})
    ctx.update(kwargs)
    _CTX.set(ctx)


def clear_log_context() -> None:
    """Reset the logging context."""
    _CTX.set({})


class JsonFormatter(logging.Formatter):
    """Formats records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as JSON.

        Args:
            record (logging.LogRecord): Record to format.

        Returns:
            str: JSON line.
        """
        ctx = _CTX.get() or {}
        out: dict[str, Any] = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for f in _FIELDS:
            out[f] = getattr(record, f, None) or ctx.get(f)
        return json.dumps(out, sort_keys=True)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger under the ``trader`` namespace.

    Args:
        name (str): Logger name suffix.

    Returns:
        logging.Logger: Configured logger.
    """
    return logging.getLogger(f"trader.{name}")


def configure_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    """
    Configure JSON logging to stderr and optionally a file.

    Args:
        log_file (Path | None): Optional ``data/logs/<run_id>.jsonl`` path.
        level (int): Logging level.
    """
    root = logging.getLogger("trader")
    root.setLevel(level)
    root.propagate = False
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(JsonFormatter())
    root.addHandler(stderr)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
