"""Trade event (journal row) contract (contract 12)."""

from __future__ import annotations

from typing import Any

from .common import DomainModel, SchemaVersion, UtcDatetime
from .enums import EventType


class TradeEvent(DomainModel):
    """One append-only, hash-chained journal event."""

    schema_version: SchemaVersion
    event_id: str
    run_id: str
    seq: int
    event_type: EventType
    event_time_utc: UtcDatetime
    recorded_at_utc: UtcDatetime
    cycle_id: str | None
    correlation_id: str | None
    payload_type: str
    payload_schema_version: str
    payload: dict[str, Any]
    prev_event_hash: str
    event_hash: str
    code_revision: str
    config_hash: str
