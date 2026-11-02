"""Owner flatten command (UD-19 option D, BL-048).

Engaging the kill switch leaves positions and their stops unchanged. Only this explicit owner
command sells, and every sell still passes the risk engine and the execution gate and is
journaled like any other order. Automation never calls it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trader.domain.ensemble import Conflict, EnsembleDecision
from trader.domain.enums import EnsembleAction, EventType, RiskStatus, Side, Sleeve
from trader.domain.signals import Invalidation, SignalCandidate
from trader.pipeline.cycle import _j, _risk_context, submit_intent
from trader.pipeline.state import RunState

OWNER_STRATEGY = "owner_command"


def flatten_all(state: RunState, t: datetime, reason: str) -> list[str]:
    """
    Cancel resting stops and pending buys, then submit exits for every open position.

    Args:
        state (RunState): Run state (market data refreshed for ``t``).
        t (datetime): Decision time (the latest processed bar close).
        reason (str): Owner's reason.

    Returns:
        list[str]: One outcome line per instrument.
    """
    cycle = state.ids.next("cyc")
    _j(state, EventType.CYCLE_STARTED, t, {"owner_flatten": reason}, cycle, ptype="OwnerFlatten")
    outcomes: list[str] = []
    for oid, intent in sorted(state.pending.items()):
        if intent.side == Side.BUY:
            state.adapter.cancel_order(oid)
            state.pending.pop(oid)
            _j(
                state,
                EventType.ORDER_CANCELED,
                t,
                {"order_intent_id": oid, "reason": "owner_flatten"},
                cycle,
                intent.correlation_id,
                "OrderCancel",
            )
    for iid in sorted(state.ledger.positions):
        corr = state.ids.next("cor")
        stop = state.stops.pop(iid, None)
        if stop is not None:
            state.adapter.cancel_order(stop.order_intent_id)
            _j(
                state,
                EventType.ORDER_CANCELED,
                t,
                {"order_intent_id": stop.order_intent_id, "reason": "owner_flatten"},
                cycle,
                corr,
                "OrderCancel",
            )
        snap = state.builder.snapshot(iid, t, cycle, state.ids.next("snp"))
        if snap.latest_bar is None:
            outcomes.append(f"{iid}: no price available; not flattened")
            continue
        sig = SignalCandidate(
            schema_version="1.0.0",
            signal_id=state.ids.next("sig"),
            correlation_id=corr,
            cycle_id=cycle,
            instrument_id=iid,
            timeframe=state.timeframe,
            decision_time_utc=t,
            strategy_id=OWNER_STRATEGY,
            strategy_version="1.0.0",
            sleeve=Sleeve.CORE,
            side=Side.SELL,
            strength=Decimal(1),
            confidence=None,
            expected_horizon=None,
            entry_reference_price=snap.latest_bar.close,
            invalidation=Invalidation(kind="owner_command", level=None, reason="OWNER_FLATTEN"),
            feature_set_id="none",
            regime_assessment_id="none",
            model_id=None,
            model_version=None,
            rationale_codes=["OWNER_FLATTEN"],
        )
        _j(
            state,
            EventType.FEATURES_COMPUTED,
            t,
            {"snapshot": snap, "features": None},
            cycle,
            corr,
            "SnapshotAndFeatures",
        )
        _j(state, EventType.SIGNAL_GENERATED, t, sig, cycle, corr)
        dec = EnsembleDecision(
            schema_version="1.0.0",
            ensemble_decision_id=state.ids.next("ens"),
            correlation_id=corr,
            cycle_id=cycle,
            instrument_id=iid,
            decision_time_utc=t,
            action=EnsembleAction.EXIT_LONG,
            position_state="long",
            contributing_signal_ids=[sig.signal_id],
            ignored_signals=[],
            combined_score=None,
            confidence=None,
            conflict=Conflict(detected=False, buy_votes=0, sell_votes=1),
            no_trade_reason=None,
            ensemble_id="owner_flatten",
            ensemble_version="1.0.0",
            weighting_method="owner_command",
            regime_assessment_id="none",
        )
        _j(state, EventType.ENSEMBLE_DECIDED, t, dec, cycle, corr)
        ctx = _risk_context(state, t, snap, None, None, [sig])
        ctx.owner_flatten = True
        rd = state.engine.evaluate(dec, ctx)
        state.decisions[rd.risk_decision_id] = rd
        _j(state, EventType.RISK_EVALUATED, t, rd, cycle, corr)
        if rd.status == RiskStatus.REJECTED:
            outcomes.append(f"{iid}: rejected {[c.value for c in rd.reason_codes]}")
            continue
        exit_intent = state.engine.build_order_intent(rd, ctx)
        assert exit_intent is not None
        state.owner_flatten_decision_ids.add(rd.risk_decision_id)
        rep = submit_intent(state, exit_intent, rd, t)
        outcomes.append(
            f"{iid}: sell {exit_intent.quantity} " + ("submitted" if rep else "REJECTED")
        )
    _j(
        state,
        EventType.CYCLE_COMPLETED,
        t,
        {"owner_flatten": reason, "outcomes": outcomes},
        cycle,
        ptype="OwnerFlatten",
    )
    return outcomes or ["no open positions"]
