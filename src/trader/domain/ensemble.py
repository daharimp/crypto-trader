"""Ensemble decision contract (contract 7)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import model_validator

from .common import DomainModel, SchemaVersion, UtcDatetime
from .enums import EnsembleAction, NoTradeReason


class IgnoredSignal(DomainModel):
    """A signal the ensemble did not use, with the reason."""

    signal_id: str
    reason: str


class Conflict(DomainModel):
    """Vote summary for conflict detection."""

    detected: bool
    buy_votes: int
    sell_votes: int


class EnsembleDecision(DomainModel):
    """Combined action per instrument and cycle."""

    schema_version: SchemaVersion
    ensemble_decision_id: str
    correlation_id: str
    cycle_id: str
    instrument_id: str
    decision_time_utc: UtcDatetime
    action: EnsembleAction
    position_state: Literal["flat", "long"]
    contributing_signal_ids: list[str]
    ignored_signals: list[IgnoredSignal]
    combined_score: Decimal | None
    confidence: Decimal | None
    conflict: Conflict
    no_trade_reason: NoTradeReason | None
    ensemble_id: str
    ensemble_version: str
    weighting_method: str
    regime_assessment_id: str

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        """
        Check action, reason, and position consistency.

        Returns:
            EnsembleDecision: The validated decision.

        Raises:
            ValueError: If the action contradicts the position or reason.
        """
        if self.action == EnsembleAction.NO_TRADE and self.no_trade_reason is None:
            raise ValueError("no_trade requires no_trade_reason")
        if self.action == EnsembleAction.ENTER_LONG and self.position_state != "flat":
            raise ValueError("enter_long requires position_state flat")
        if self.action == EnsembleAction.EXIT_LONG and self.position_state != "long":
            raise ValueError("exit_long requires position_state long")
        return self
