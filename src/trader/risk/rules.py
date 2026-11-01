"""Gate rules RR-01 to RR-12 (architecture.md §6.7). Each returns a RuleResult."""

from __future__ import annotations

from trader.domain.enums import (
    Environment,
    EventType,
    OrderPurpose,
    Provenance,
    ReasonCode,
    RuleOutcome,
    Side,
    Sleeve,
)
from trader.domain.risk import RuleResult

from .context import RiskContext
from .controls import Cooldowns
from .intents import idempotency_key

RULE_VERSION = "1.0.0"
R = ReasonCode


def result(
    rule_id: str, outcome: RuleOutcome, code: ReasonCode | None = None, **detail: object
) -> RuleResult:
    """
    Build a RuleResult with stringified detail.

    Args:
        rule_id (str): Rule ID.
        outcome (RuleOutcome): Outcome.
        code (ReasonCode | None): Reason code on failure.
        **detail: Inputs and thresholds.

    Returns:
        RuleResult: Result.
    """
    return RuleResult(
        rule_id=rule_id,
        rule_version=RULE_VERSION,
        outcome=outcome,
        reason_code=code,
        detail={k: str(v) for k, v in detail.items()},
    )


def ok(rule_id: str, **detail: object) -> RuleResult:
    """
    Passing result.

    Args:
        rule_id (str): Rule ID.
        **detail: Detail.

    Returns:
        RuleResult: Pass.
    """
    return result(rule_id, RuleOutcome.PASS, None, **detail)


def fail(rule_id: str, code: ReasonCode, **detail: object) -> RuleResult:
    """
    Failing result.

    Args:
        rule_id (str): Rule ID.
        code (ReasonCode): Reason code.
        **detail: Detail.

    Returns:
        RuleResult: Fail.
    """
    return result(rule_id, RuleOutcome.FAIL, code, **detail)


def rr01_profile_runnable(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-01: compiled profile runnable for this environment; profile not suspended."""
    st = ctx.profile.status
    allowed = {"validated", "active"} if ctx.environment == Environment.BACKTEST else {"active"}
    if not ctx.compiled.runnable or ctx.compiled.environment != ctx.environment:
        return fail("RR-01", R.PROFILE_NOT_RUNNABLE, runnable=ctx.compiled.runnable)
    if st not in allowed:
        return fail("RR-01", R.PROFILE_NOT_RUNNABLE, status=st)
    return ok("RR-01", status=st)


def rr02_config_resolved(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-02: no blockers; paper accepts only approved or hypothesis values."""
    if ctx.compiled.blockers or ctx.params is None:
        refs = sorted({b.ref for b in ctx.compiled.blockers})
        return fail("RR-02", R.RISK_CONFIG_UNRESOLVED, blockers=",".join(refs) or "params")
    if ctx.environment == Environment.PAPER:
        bad = [
            k
            for k, v in ctx.compiled.effective.items()
            if v.provenance in (Provenance.EXPERIMENT, Provenance.FIXTURE)
        ]
        if bad:
            return fail("RR-02", R.RISK_CONFIG_UNRESOLVED, non_approved=",".join(bad))
    return ok("RR-02")


def rr03_execution_enabled(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-03: kill switch disengaged; paper_autonomous; execution flag on."""
    if ctx.controls.kill_switch.engaged:
        return fail("RR-03", R.KILL_SWITCH_ENGAGED, reason=ctx.controls.kill_switch.reason)
    if ctx.profile.execution.autonomy_mode != "paper_autonomous":
        return fail("RR-03", R.EXECUTION_DISABLED, autonomy=ctx.profile.execution.autonomy_mode)
    if not ctx.controls.execution_enabled:
        return fail("RR-03", R.EXECUTION_DISABLED, execution_enabled=False)
    return ok("RR-03")


def rr04_safety(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-04: safety constants hold (defence in depth; the schema already forbids them)."""
    ex = ctx.profile.execution
    safe = (
        ctx.profile.capital.funds == "simulated"
        and list(ex.instrument_types) == ["spot"]
        and not any(
            (
                ex.real_money_enabled,
                ex.leverage_allowed,
                ex.margin_allowed,
                ex.short_selling_allowed,
                ex.withdrawals_allowed,
                ex.transfers_allowed,
            )
        )
    )
    return ok("RR-04") if safe else fail("RR-04", R.SAFETY_VIOLATION)


def rr05_instrument(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-05: in registry, spot, in scope, not blocked/disallowed, eligible at t."""
    iid = ctx.snapshot.instrument_id
    inst = ctx.registry.instrument(iid)
    if inst is None or ctx.registry.asset(inst.base) is None:
        return fail("RR-05", R.ASSET_NOT_SUPPORTED, instrument=iid, why="not_in_registry")
    if inst.type != "spot":
        return fail("RR-05", R.ASSET_NOT_SUPPORTED, instrument=iid, why="not_spot")
    if iid not in ctx.profile.universe.instruments_in_scope:
        return fail("RR-05", R.ASSET_NOT_SUPPORTED, instrument=iid, why="outside_profile")
    asset = ctx.registry.asset(inst.base)
    if asset is None or asset.blocked or asset.asset_id in ctx.profile.universe.disallowed_assets:
        return fail("RR-05", R.ASSET_BLOCKED, instrument=iid)
    elig = ctx.universe.assets.get(iid) if ctx.universe else None
    if elig is None or not elig.eligible:
        why = elig.reason if elig else "not_evaluated"
        return fail("RR-05", R.ASSET_INELIGIBLE, instrument=iid, why=why)
    return ok("RR-05", instrument=iid, tier=asset.tier)


def rr06_fresh(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-06: snapshot fresh and quality ok."""
    s = ctx.snapshot
    if not s.is_fresh:
        return fail("RR-06", R.STALE_DATA, expected_close=s.expected_latest_close_utc)
    if s.quality_status != "ok":
        return fail("RR-06", R.DATA_QUALITY_FAILED)
    return ok("RR-06", latest_close=s.expected_latest_close_utc)


def rr07_duplicate(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-07: key unused; no pending market order; entries only when flat."""
    iid = ctx.snapshot.instrument_id
    side, purpose = (Side.BUY, OrderPurpose.ENTRY) if entry else (Side.SELL, OrderPurpose.EXIT)
    key = idempotency_key(ctx.compiled.config_hash, iid, side, purpose, ctx.decision_time)
    if key in ctx.used_idempotency_keys:
        return fail("RR-07", R.DUPLICATE_ORDER, why="idempotency_key_used")
    if any(
        o.instrument_id == iid and o.purpose != OrderPurpose.PROTECTIVE_STOP for o in ctx.pending
    ):
        return fail("RR-07", R.DUPLICATE_ORDER, why="pending_market_order")
    if entry and ctx.held_quantity(iid) > 0:
        return fail("RR-07", R.DUPLICATE_ORDER, why="already_long")
    return ok("RR-07")


def rr08_spot(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-08: buys within available cash; sells within held quantity."""
    if entry:
        avail = ctx.position.cash_usd - ctx.position.committed_cash_usd
        if avail <= 0:
            return fail("RR-08", R.SPOT_CONSTRAINT_VIOLATION, available_cash=avail)
        return ok("RR-08", available_cash=avail)
    held = ctx.held_quantity(ctx.snapshot.instrument_id)
    if held <= 0:
        return fail("RR-08", R.SPOT_CONSTRAINT_VIOLATION, held=held)
    return ok("RR-08", held=held)


def rr09_breaker(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-09: drawdown >= breaker opens the latched breaker; an open breaker rejects."""
    assert ctx.params is not None
    dd, b = ctx.loss.drawdown_pct, ctx.params.breaker_pct
    if dd >= b and ctx.controls.breaker.trip(ctx.decision_time):
        ctx.controls.emit(
            EventType.CIRCUIT_BREAKER_OPENED, {"drawdown_pct": str(dd), "breaker_pct": str(b)}
        )
    if ctx.controls.breaker.open:
        return fail("RR-09", R.CIRCUIT_BREAKER_OPEN, drawdown_pct=dd, breaker_pct=b)
    return ok("RR-09", drawdown_pct=dd, breaker_pct=b)


def rr10_daily(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-10: daily loss since 00:00 UTC below the limit; else lock out until midnight."""
    assert ctx.params is not None
    loss_pct = -ctx.loss.daily_pnl_pct
    limit = ctx.params.daily_loss_pct
    lock = ctx.controls.lockout
    if not lock.active(ctx.decision_time) and loss_pct >= limit:
        until = lock.start(ctx.decision_time)
        ctx.controls.emit(
            EventType.DAILY_LOCKOUT_STARTED,
            {"until": until.isoformat(), "daily_loss_pct": str(loss_pct)},
        )
    if lock.active(ctx.decision_time):
        return fail(
            "RR-10", R.DAILY_LOSS_LIMIT, daily_loss_pct=loss_pct, limit=limit, until=lock.until
        )
    return ok("RR-10", daily_loss_pct=loss_pct, limit=limit)


def rr11_cooldown(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-11: no active cooldown for the strategy-instrument pair."""
    for s in ctx.signals:
        key = Cooldowns.key(s.strategy_id, ctx.snapshot.instrument_id)
        if ctx.controls.cooldowns.active(key, ctx.decision_time):
            return fail(
                "RR-11", R.COOLDOWN_ACTIVE, key=key, until=ctx.controls.cooldowns.until[key]
            )
    return ok("RR-11")


def rr12_intraday(ctx: RiskContext, entry: bool) -> RuleResult:
    """RR-12: intraday sleeve signals need an enabled sleeve (always disabled in M1)."""
    if any(s.sleeve == Sleeve.INTRADAY for s in ctx.signals):
        return fail("RR-12", R.INTRADAY_SLEEVE_DISABLED)
    return ok("RR-12")


GATE_RULES = [
    ("RR-01", rr01_profile_runnable, True),
    ("RR-02", rr02_config_resolved, True),
    ("RR-03", rr03_execution_enabled, True),
    ("RR-04", rr04_safety, True),
    ("RR-05", rr05_instrument, False),
    ("RR-06", rr06_fresh, True),
    ("RR-07", rr07_duplicate, True),
    ("RR-08", rr08_spot, True),
    ("RR-09", rr09_breaker, False),
    ("RR-10", rr10_daily, False),
    ("RR-11", rr11_cooldown, False),
    ("RR-12", rr12_intraday, False),
]
"""(rule_id, function, applies_to_exits)."""
