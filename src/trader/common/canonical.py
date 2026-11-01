"""Canonical JSON serialization used for hashing (§7.1)."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

from .clock import format_utc


def to_canonical_obj(value: Any) -> Any:
    """
    Convert a value to plain JSON-compatible data using canonical conventions.

    Decimals become strings, datetimes become ``YYYY-MM-DDTHH:MM:SSZ``, enums become their
    values, and Pydantic models become dicts.

    Args:
        value (Any): Value to convert.

    Returns:
        Any: JSON-compatible structure.
    """
    if isinstance(value, BaseModel):
        return to_canonical_obj(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return format_utc(value)
    if isinstance(value, dict):
        return {str(k): to_canonical_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_canonical_obj(v) for v in value]
    if isinstance(value, float):
        # Reason: floats are not allowed in hashed content; route them through Decimal(str())
        # so 0.1 serializes as "0.1" rather than a binary artefact.
        return format(Decimal(str(value)), "f")
    return value


def canonical_json(value: Any) -> str:
    """
    Serialize a value to canonical JSON text.

    Args:
        value (Any): Value to serialize.

    Returns:
        str: UTF-8 JSON with sorted keys and compact separators.
    """
    return json.dumps(
        to_canonical_obj(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
