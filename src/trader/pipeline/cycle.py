"""One decision cycle and the bar-level steps around it (handoff §5.2).

Stages (D-29): snapshot -> universe -> features -> regime -> signals -> ensemble ->
risk decision -> order intent (journaled first) -> execution gate -> simulated adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from trader.common.logging import get_logger, set_log_context
from trader.domain.enums import (
    EnsembleAction,
    EventType,
    ExecutionStatus,
    OrderPurpose,
    RiskStatus,
)
from trader.domain.execution import ExecutionReport
from trader.domain.orders import OrderIntent
from trader.domain.risk import RiskDecision
from trader.ensemble.passthrough import decide
from trader.execution.gate import GateContext
from trader.features.definitions import FEATURE_WINDOW_BARS
from trader.features.pipeline import compute_features
from trader.journal.store import JournalWriteError
from trader.regimes.null_classifier import assess
from trader.risk.context import RiskContext
from trader.risk.controls import Cooldowns
from trader.strategies.base import SignalIds

from .state import RunState

log = get_logger("cycle")
_LOGGED = {
    EventType.RISK_EVALUATED,
    EventType.ORDER_SUBMITTED,
    EventType.ORDER_REJECTED,
    EventType.ORDER_FILLED,
    EventType.STOP_TRIGGERED,
    EventType.KILL_SWITCH_ENGAGED,
    EventType.RECONCILIATION_FAILED,
    EventType.CIRCUIT_BREAKER_OPENED,
    EventType.DAILY_LOCKOUT_STARTED,
    EventType.COOLDOWN_STARTED,
}


class RunFailedError(RuntimeError):
    """Raised when the run must stop (e.g. journal write failure, exit 1)."""


def _j(
    state: RunState,
    et: EventType,
    t: datetime,
    payload: Any,
    cycle: str | None = None,
    corr: str | None = None,
    ptype: str | None = None,
) -> None:
    """
    Journal an event; a failure engages the kill switch and fails the run.

    Args:
        state (RunState): Run state.
        et (EventType): Event type.
        t (datetime): Event time.
        payload (Any): Payload.
        cycle (str | None): Cycle ID.
        corr (str | None): Correlation ID.
        ptype (str | None): Payload type override.

    Raises:
        RunFailedError: If the journal write fails (journal-before-act, R-05).
    """
    try:
        state.journal.append(et, t, payload, cycle, corr, ptype)
        if et in _LOGGED:
            log.info(
                et.value, extra={"event_type": et.value, "cycle_id": cycle, "correlation_id": corr}
            )
    except JournalWriteError as exc:
        state.controls.kill_switch.engage("journal write failure", "journal_write_failure")
        raise RunFailedError(f"journal write failed: {exc}") from exc


def _drain(state: RunState, t: datetime, cycle: str | None = None) -> None:
    """
    Journal queued control events.

    Args:
        state (RunState): Run state.
        t (datetime): Time.
        cycle (str | None): Cycle ID.
    """
    for et, payload in state.controls.drain():
        _j(state, et, t, payload, cycle, ptype="ControlEvent")


def _engage(state: RunState, t: datetime, reason: str, trigger: str) -> None:
    """
    Auto-engage the run kill switch (automation can only engage).

    Args:
        state (RunState): Run state.
        t (datetime): Time.
        reason (str): Reason.
        trigger (str): Trigger name.
    """
    if state.controls.kill_switch.engage(reason, trigger):
        _j(
            state,
            EventType.KILL_SWITCH_ENGAGED,
            t,
            {"reason": reason, "trigger": trigger},
            ptype="KillSwitchEvent",
        )


def _gate_ctx(state: RunState, now: datetime) -> GateContext:
    """
    Build the gate context.

    Args:
        state (RunState): Run state.
        now (datetime): Submission time.

    Returns:
        GateContext: Context sharing the run's idempotency keys.
    """
    return GateContext(
        kill_switch_engaged=state.controls.kill_switch.engaged,
        execution_enabled=state.controls.execution_enabled,
        now=now,
        adapter_id=state.adapter.adapter_id,
        used_idempotency_keys=state.used_keys,
        filled_entry_ids=state.filled_entries,
    )


def submit_intent(
    state: RunState, intent: OrderIntent, rd: RiskDecision | None, now: datetime
) -> ExecutionReport | None:
    """
    Journal an intent FIRST, then gate-check and submit it.

    Args:
        state (RunState): Run state.
        intent (OrderIntent): Intent.
        rd (RiskDecision | None): Its risk decision.
        now (datetime): Submission time.

    Returns:
        ExecutionReport | None: Adapter report, or None if rejected.
    """
    _j(state, EventType.ORDER_INTENT_CREATED, now, intent, intent.cycle_id, intent.correlation_id)
    state.counts["order_intents"] += 1
    res = state.execution.submit(intent, rd, _gate_ctx(state, now))
    rejected = [r.value for r in res.rejected]
    if res.report is not None and res.report.status == ExecutionStatus.REJECTED:
        rejected.append(str(res.report.reason_code))
    if rejected:
        for r in rejected:
            state.rejections[r] += 1
        _j(
            state,
            EventType.ORDER_REJECTED,
            now,
            {"order_intent_id": intent.order_intent_id, "reason_codes": rejected},
            intent.cycle_id,
            intent.correlation_id,
            "OrderRejection",
        )
        return None
    assert res.report is not None
    _j(state, EventType.ORDER_SUBMITTED, now, res.report, intent.cycle_id, intent.correlation_id)
    if intent.purpose == OrderPurpose.PROTECTIVE_STOP:
        state.stops[intent.instrument_id] = intent
    else:
        state.pending[intent.order_intent_id] = intent
    return res.report


def _risk_context(
    state: RunState, t: datetime, snap: Any, fs: Any, uni: Any, signals: list[Any]
) -> RiskContext:
    """
    Build a fresh RiskContext.

    Args:
        state (RunState): Run state.
        t (datetime): Decision time.
        snap (Any): MarketSnapshot.
        fs (Any): FeatureSet or None.
        uni (Any): UniverseSnapshot.
        signals (list[Any]): Signals for the instrument.

    Returns:
        RiskContext: Context.
    """
    return RiskContext(
        compiled=state.compiled,
        profile=state.profile,
        params=state.params,
        registry=state.registry,
        costs=state.costs,
        environment=state.environment,
        timeframe=state.timeframe,
        decision_time=t,
        position=state.position_snapshot(t),
        snapshot=snap,
        features=fs,
        universe=uni,
        signals=signals,
        controls=state.controls,
        loss=state.loss.state(
            state.params, state.controls.breaker.open, state.controls.lockout.active(t)
        ),
        ids=state.ids,
        used_idempotency_keys=state.used_keys,
        pending=list(state.pending.values()),
    )


def run_cycle(state: RunState, t: datetime) -> None:
    """
    Run one decision cycle at bar close ``t`` for every in-scope instrument.

    Args:
        state (RunState): Run state.
        t (datetime): Decision time.
    """
    cycle = state.ids.next("cyc")
    set_log_context(cycle_id=cycle)
    _j(state, EventType.CYCLE_STARTED, t, {"decision_time_utc": t}, cycle, ptype="Cycle")
    uni = state.eligibility.evaluate(t, state.ids.next("uni"))
    _j(state, EventType.UNIVERSE_EVALUATED, t, uni, cycle)
    for iid in sorted(state.profile.universe.instruments_in_scope):
        corr = state.ids.next("cor")
        set_log_context(correlation_id=corr)
        snap = state.builder.snapshot(iid, t, cycle, state.ids.next("snp"))
        window = state.builder.window(iid, t, FEATURE_WINDOW_BARS)
        fs = (
            compute_features(
                window, iid, state.timeframe, t, state.ids.next("fs"), snap.dataset_ids
            )
            if window
            else None
        )
        _j(
            state,
            EventType.FEATURES_COMPUTED,
            t,
            {"snapshot": snap, "features": fs},
            cycle,
            corr,
            "SnapshotAndFeatures",
        )
        if not snap.is_fresh:
            _j(
                state,
                EventType.DATA_STALE,
                t,
                {"instrument_id": iid, "expected_close": snap.expected_latest_close_utc},
                cycle,
                corr,
                "DataStale",
            )
        regime = assess(snap, fs, state.ids.next("rg"))
        _j(state, EventType.REGIME_ASSESSED, t, regime, cycle, corr)
        signals = []
        if fs is not None:
            signals = state.strategy.generate(
                snap, fs, regime, SignalIds(state.ids.next("sig"), corr, cycle)
            )
        for s in signals:
            _j(state, EventType.SIGNAL_GENERATED, t, s, cycle, corr)
        pos = state.ledger.positions.get(iid)
        dec = decide(
            signals,
            regime,
            "long" if pos else "flat",
            pos.owners if pos else [],
            state.ids.next("ens"),
            corr,
            cycle,
        )
        _j(state, EventType.ENSEMBLE_DECIDED, t, dec, cycle, corr)
        if dec.action not in (EnsembleAction.ENTER_LONG, EnsembleAction.EXIT_LONG):
            continue
        used = [s for s in signals if s.signal_id in dec.contributing_signal_ids]
        ctx = _risk_context(state, t, snap, fs, uni, used)
        rd = state.engine.evaluate(dec, ctx)
        state.decisions[rd.risk_decision_id] = rd
        _j(state, EventType.RISK_EVALUATED, t, rd, cycle, corr)
        _drain(state, t, cycle)
        if rd.status == RiskStatus.REJECTED:
            for code in rd.reason_codes:
                state.rejections[code.value] += 1
            continue
        intent = state.engine.build_order_intent(rd, ctx)
        if intent is not None:
            submit_intent(state, intent, rd, t)
    _j(state, EventType.CYCLE_COMPLETED, t, {"decision_time_utc": t}, cycle, ptype="Cycle")
    set_log_context(cycle_id=None, correlation_id=None)


def _after_fill(state: RunState, intent: OrderIntent, rep: ExecutionReport, t: datetime) -> None:
    """
    Book a fill: ledger, stops, cooldowns, journal.

    Args:
        state (RunState): Run state.
        intent (OrderIntent): Filled intent.
        rep (ExecutionReport): Fill report.
        t (datetime): Time.
    """
    tier = state.registry.tier_of(intent.instrument_id) or "unknown"
    trade = state.ledger.apply_fill(intent, rep, tier)
    state.counts["fills"] += 1
    state.controls.consecutive_errors = 0
    _j(state, EventType.ORDER_FILLED, t, rep, intent.cycle_id, intent.correlation_id)
    iid = intent.instrument_id
    if intent.purpose == OrderPurpose.ENTRY:
        state.filled_entries.add(intent.order_intent_id)
        rd = state.decisions[intent.risk_decision_id]
        ctx = _risk_context(
            state, t, state.builder.snapshot(iid, t, intent.cycle_id, "snp-fill"), None, None, []
        )
        stop = state.engine.build_protective_stop_intent(intent, rep, rd, ctx)
        if submit_intent(state, stop, rd, t) is not None:
            state.ledger.set_stop(iid, stop.stop_price)
    else:
        resting = state.stops.pop(iid, None)
        if resting is not None and resting.order_intent_id != intent.order_intent_id:
            state.adapter.cancel_order(resting.order_intent_id)
            _j(
                state,
                EventType.ORDER_CANCELED,
                t,
                {"order_intent_id": resting.order_intent_id, "reason": "position_exited"},
                resting.cycle_id,
                resting.correlation_id,
                "OrderCancel",
            )
        if trade is not None and state.params is not None:
            state.counts["closed_trades"] += 1
            for sid in trade.strategy_ids:
                key = Cooldowns.key(sid, iid)
                until = state.controls.cooldowns.record_exit(
                    key, trade.pnl_usd, t, state.params.cooldown_count, state.params.cooldown_hours
                )
                if until is not None:
                    _j(
                        state,
                        EventType.COOLDOWN_STARTED,
                        t,
                        {"key": key, "until": until},
                        ptype="ControlEvent",
                    )
    _j(
        state,
        EventType.POSITION_UPDATED,
        t,
        state.position_snapshot(t),
        intent.cycle_id,
        intent.correlation_id,
    )


def _handle_reports(
    state: RunState, reports: list[tuple[OrderIntent, ExecutionReport]], t: datetime
) -> None:
    """
    Process adapter reports, then reconcile.

    Args:
        state (RunState): Run state.
        reports (list[tuple[OrderIntent, ExecutionReport]]): Reports.
        t (datetime): Time.
    """
    for intent, rep in reports:
        state.pending.pop(intent.order_intent_id, None)
        if rep.status == ExecutionStatus.FILLED:
            _after_fill(state, intent, rep, t)
        elif rep.status == ExecutionStatus.EXPIRED:
            state.rejections[str(rep.reason_code)] += 1
            _j(state, EventType.ORDER_CANCELED, t, rep, intent.cycle_id, intent.correlation_id)
        else:
            state.controls.consecutive_errors += 1
            state.rejections[str(rep.reason_code)] += 1
            _j(state, EventType.EXECUTION_ERROR, t, rep, intent.cycle_id, intent.correlation_id)
            limit = state.params.max_consecutive_errors if state.params else 1
            if state.controls.consecutive_errors >= limit:
                _engage(state, t, "repeated execution errors", "repeated_execution_errors")
    if reports:
        reconcile(state, t)


def reconcile(state: RunState, t: datetime) -> bool:
    """
    Reconcile ledger and adapter; a mismatch engages the kill switch.

    Args:
        state (RunState): Run state.
        t (datetime): Time.

    Returns:
        bool: True if reconciled.
    """
    diffs = state.ledger.reconcile(state.adapter.get_balances())
    if not diffs:
        return True
    _j(state, EventType.RECONCILIATION_FAILED, t, {"differences": diffs}, ptype="Reconciliation")
    _engage(state, t, "reconciliation mismatch", "reconciliation_mismatch")
    return False


def process_open(state: RunState, t0: datetime) -> None:
    """
    Step 1: fill market orders decided at ``t0`` at this bar's open (exits first).

    Args:
        state (RunState): Run state.
        t0 (datetime): Bar open time.
    """
    bars = {i: state.builder.bar_at_open(i, t0) for i in state.builder.instruments}
    _handle_reports(state, state.adapter.fill_market_orders(bars, t0), t0)


def process_stops(state: RunState, t0: datetime) -> None:
    """
    Step 2: trigger resting protective stops inside the bar.

    Args:
        state (RunState): Run state.
        t0 (datetime): Bar open time.
    """
    bars = {i: state.builder.bar_at_open(i, t0) for i in state.builder.instruments}
    fills = state.adapter.trigger_stops(bars)
    for intent, rep in fills:
        if rep.status == ExecutionStatus.FILLED:
            state.stops.pop(intent.instrument_id, None)
            _j(state, EventType.STOP_TRIGGERED, t0, rep, intent.cycle_id, intent.correlation_id)
    _handle_reports(state, fills, t0)


def mark_to_market(state: RunState, t1: datetime) -> None:
    """
    Step 3: mark at the bar close and update loss state and the breaker latch.

    Args:
        state (RunState): Run state.
        t1 (datetime): Bar close time.
    """
    closes = {}
    for i in state.builder.instruments:
        w = state.builder.window(i, t1, 1)
        if w:
            closes[i] = w[-1].close
    state.ledger.mark(closes)
    state.loss.mark(t1, state.ledger.equity)
    if state.params is not None and state.loss.drawdown_pct >= state.params.breaker_pct:
        if state.controls.breaker.trip(t1):
            state.controls.emit(
                EventType.CIRCUIT_BREAKER_OPENED,
                {
                    "drawdown_pct": str(state.loss.drawdown_pct),
                    "breaker_pct": str(state.params.breaker_pct),
                },
            )
    _drain(state, t1)
