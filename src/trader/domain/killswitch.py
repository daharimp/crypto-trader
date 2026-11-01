"""Kill-switch state contract (D-35)."""

from __future__ import annotations

from typing import Literal

from .common import DomainModel, SchemaVersion, UtcDatetime


class KillSwitchState(DomainModel):
    """One appended kill-switch state change."""

    schema_version: SchemaVersion
    state: Literal["engaged", "disengaged"]
    changed_at_utc: UtcDatetime
    changed_by: Literal["owner", "system"]
    reason: str
    trigger: str | None
