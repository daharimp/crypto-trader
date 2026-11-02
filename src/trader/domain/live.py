"""Live-trading authorization contract (ADR-023)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field

from .common import TBD, DomainModel, SchemaVersion
from .params import CountParam, ParamBase


class LiveAcknowledgement(DomainModel):
    """The owner's own words accepting real-money risk."""

    acknowledged_by: Annotated[str, Field(min_length=1)]
    acknowledged_at_utc: Annotated[
        str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
    ]
    statement: Annotated[str, Field(min_length=40)]


class CapitalCap(ParamBase):
    """Maximum USD the bot may manage (UD-22)."""

    value: TBD | Annotated[Decimal, Field(gt=0, le=1_000_000)]

    def is_tbd(self) -> bool:
        """Return True when unresolved."""
        return self.value == "TBD"

    def resolved_value(self) -> Any:
        """Return the value."""
        return self.value


class LiveAuthorization(DomainModel):
    """``configs/live/authorization.yaml``. Every live run re-checks it."""

    schema_version: SchemaVersion
    kind: Literal["LiveAuthorization"]
    version: Annotated[int, Field(ge=1)]
    exchange: Literal["kraken"]
    account_type: Literal["spot_dedicated"]
    max_capital_usd: CapitalCap
    min_paper_cycles_before_live: CountParam
    api_key_env: dict[Literal["key", "secret"], str]
    acknowledgement: LiveAcknowledgement | None = None
