"""Shared domain conventions (§7.1): frozen strict models, UTC datetimes, Decimals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict


def _require_utc(value: datetime) -> datetime:
    """
    Reject naive datetimes and normalize aware ones to UTC.

    Args:
        value (datetime): Parsed datetime.

    Returns:
        datetime: UTC datetime.

    Raises:
        ValueError: ``NAIVE_TIMESTAMP`` when no timezone is present.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
SchemaVersion = Literal["1.0.0"]
TBD = Literal["TBD"]


class DomainModel(BaseModel):
    """Base for every contract: unknown fields are rejected and instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionRef(DomainModel):
    """Reference to a versioned artefact (strategy, model, profile)."""

    id: str
    version: str
