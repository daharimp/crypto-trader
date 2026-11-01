"""Feature set contract (contract 4)."""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import model_validator

from .common import DomainModel, SchemaVersion, UtcDatetime


class FeatureSet(DomainModel):
    """Causal features for one instrument at one decision time."""

    schema_version: SchemaVersion
    feature_set_id: str
    instrument_id: str
    timeframe: str
    as_of_utc: UtcDatetime
    feature_set_version: str
    definitions_hash: str
    values: dict[str, Decimal | None]
    max_input_close_time_utc: UtcDatetime
    warmup_complete: bool
    input_dataset_ids: list[str]

    @model_validator(mode="after")
    def _causal(self) -> Self:
        """
        Reject features that used data from after ``as_of_utc`` (LA-02).

        Returns:
            FeatureSet: The validated feature set.

        Raises:
            ValueError: On look-ahead.
        """
        if self.max_input_close_time_utc > self.as_of_utc:
            raise ValueError("feature inputs close after as_of_utc (look-ahead)")
        return self
