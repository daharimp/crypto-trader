"""Single-strategy pass-through ensemble (M1, D-29 step 5)."""

from __future__ import annotations

from trader.domain.ensemble import Conflict, EnsembleDecision, IgnoredSignal
from trader.domain.enums import DataState, EnsembleAction, NoTradeReason, Side
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import SignalCandidate

ENSEMBLE_ID = "single_strategy_passthrough"
ENSEMBLE_VERSION = "1.0.0"


def decide(
    signals: list[SignalCandidate],
    regime: RegimeAssessment,
    position_state: str,
    owner_strategy_ids: list[str],
    decision_id: str,
    correlation_id: str,
    cycle_id: str,
) -> EnsembleDecision:
    """
    Map one strategy's signal and the position state to an action.

    Args:
        signals (list[SignalCandidate]): Signals for the instrument (0 or 1 in M1).
        regime (RegimeAssessment): Regime assessment.
        position_state (str): ``flat`` or ``long``.
        owner_strategy_ids (list[str]): Strategies that own the open position.
        decision_id (str): Decision ID.
        correlation_id (str): Correlation ID.
        cycle_id (str): Cycle ID.

    Returns:
        EnsembleDecision: Decision.
    """
    action, reason = EnsembleAction.HOLD, None
    used: list[str] = []
    ignored: list[IgnoredSignal] = []
    sig = signals[0] if signals else None
    if regime.data_state == DataState.STALE:
        action, reason = EnsembleAction.NO_TRADE, NoTradeReason.DATA_STALE
        ignored = [IgnoredSignal(signal_id=s.signal_id, reason="DATA_STALE") for s in signals]
    elif sig is not None:
        if position_state == "flat" and sig.side == Side.BUY:
            action, used = EnsembleAction.ENTER_LONG, [sig.signal_id]
        elif (
            position_state == "long"
            and sig.side == Side.SELL
            and sig.strategy_id in owner_strategy_ids
        ):
            action, used = EnsembleAction.EXIT_LONG, [sig.signal_id]
        else:
            ignored = [IgnoredSignal(signal_id=sig.signal_id, reason="NO_ACTION_FOR_POSITION")]
        ignored += [
            IgnoredSignal(signal_id=s.signal_id, reason="SINGLE_STRATEGY_ONLY") for s in signals[1:]
        ]
    buys = sum(1 for s in signals if s.side == Side.BUY)
    return EnsembleDecision(
        schema_version="1.0.0",
        ensemble_decision_id=decision_id,
        correlation_id=correlation_id,
        cycle_id=cycle_id,
        instrument_id=regime.instrument_id,
        decision_time_utc=regime.as_of_utc,
        action=action,
        position_state="long" if position_state == "long" else "flat",
        contributing_signal_ids=used,
        ignored_signals=ignored,
        combined_score=None,
        confidence=None,
        conflict=Conflict(detected=False, buy_votes=buys, sell_votes=len(signals) - buys),
        no_trade_reason=reason,
        ensemble_id=ENSEMBLE_ID,
        ensemble_version=ENSEMBLE_VERSION,
        weighting_method="single_strategy",
        regime_assessment_id=regime.regime_assessment_id,
    )
