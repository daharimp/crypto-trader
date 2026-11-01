"""Cross-field policy rules PV-01 to PV-09 and RP-01 to RP-07."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from trader.domain.compiled import EffectiveValue
from trader.domain.enums import Environment, ValidationErrorCode
from trader.domain.profiles import TradingProfile
from trader.domain.risk_profile import RiskProfile

E = ValidationErrorCode


def _err(code: ValidationErrorCode, rule: str, msg: str) -> str:
    """
    Format an error string.

    Args:
        code (ValidationErrorCode): Error code.
        rule (str): Rule ID.
        msg (str): Message.

    Returns:
        str: ``CODE [RULE]: message``.
    """
    return f"{code.value} [{rule}]: {msg}"


def check_trading_profile(
    profile: TradingProfile, environment: Environment, has_activation_record: bool = False
) -> list[str]:
    """
    Apply PV-01, PV-02, PV-03, PV-06, PV-07, PV-08, and PV-09.

    Args:
        profile (TradingProfile): Parsed profile.
        environment (Environment): Requested environment.
        has_activation_record (bool): Whether a matching activation record exists (never
            in M1; activation is BL-028).

    Returns:
        list[str]: Error strings (empty if all pass).
    """
    errors: list[str] = []
    u = profile.universe
    allow = {a.asset_id for a in u.manual_allowlist}
    overlap = set(u.disallowed_assets) & (set(u.core_assets) | allow)
    if overlap:
        errors.append(
            _err(E.PROFILE_CONTRADICTION, "PV-01", f"disallowed and allowed: {sorted(overlap)}")
        )
    for inst in u.instruments_in_scope:
        base, quote = inst.split("-", 1)
        if base not in set(u.core_assets) | allow or quote != u.quote_currency:
            errors.append(
                _err(E.PROFILE_CONTRADICTION, "PV-02", f"{inst} not in core/allowlist or not USD")
            )
    rs = profile.risk_selection
    if rs.risk_profile_id == "aggressive" and rs.aggressive_acknowledgement is None:
        errors.append(
            _err(E.AGGRESSIVE_NOT_ACKNOWLEDGED, "PV-03", "aggressive needs acknowledgement")
        )
    md = profile.horizon.minute_data
    if md.entry_exit_refinement_enabled:
        # Reason: no 1m candle source is registered in M1, so refinement can never be valid.
        errors.append(
            _err(E.PROFILE_CONTRADICTION, "PV-06", "refinement needs a registered 1m source")
        )
    for src in profile.data_sources.active:
        if src.required_for_trading and src.tier != "V1":
            errors.append(
                _err(E.DATA_SOURCE_NOT_PERMITTED, "PV-07", f"{src.source_id} is not tier V1")
            )
    errors.extend(_check_status(profile, environment, has_activation_record))
    if u.core_assets and "core" not in u.allowed_tiers:
        errors.append(_err(E.PROFILE_CONTRADICTION, "PV-09", "allowed_tiers must include core"))
    return errors


def _check_status(
    profile: TradingProfile, environment: Environment, has_activation_record: bool
) -> list[str]:
    """
    Apply PV-08 (declared status is re-verified at every load).

    Args:
        profile (TradingProfile): Parsed profile.
        environment (Environment): Requested environment.
        has_activation_record (bool): Whether an activation record exists.

    Returns:
        list[str]: Errors.
    """
    out: list[str] = []
    if environment.value not in profile.execution.permitted_environments:
        out.append(_err(E.PROFILE_NOT_RUNNABLE, "PV-08", f"{environment} not permitted"))
    if profile.status in ("draft", "suspended"):
        out.append(_err(E.PROFILE_NOT_RUNNABLE, "PV-08", f"status {profile.status} cannot run"))
    elif environment in (Environment.PAPER, Environment.LIVE):
        env = environment.value
        if profile.status != "active":
            out.append(_err(E.PROFILE_NOT_RUNNABLE, "PV-08", f"{env} requires status active"))
        elif not has_activation_record:
            out.append(
                _err(
                    E.PROFILE_NOT_RUNNABLE,
                    "PV-08",
                    f"{env} requires an activation "
                    f"record (trader profile activate --environment {env})",
                )
            )
    return out


def check_intraday(profile: TradingProfile, risk: RiskProfile) -> list[str]:
    """
    Apply PV-05: intraday strategies need the role and an approved intraday cap.

    Args:
        profile (TradingProfile): Parsed profile.
        risk (RiskProfile): Selected risk profile.

    Returns:
        list[str]: Errors.
    """
    md = profile.horizon.minute_data
    if not md.intraday_strategies_enabled:
        return []
    cap = risk.allocation.intraday_allocation_cap_pct
    if "approved_intraday_strategies" not in md.permitted_roles or cap.status != "approved":
        return [_err(E.INTRADAY_NOT_APPROVED, "PV-05", "intraday needs an approved cap (UD-14)")]
    return []


def _num(eff: dict[str, EffectiveValue], key: str, sub: str | None = None) -> Decimal | None:
    """
    Read a resolved numeric effective value.

    Args:
        eff (dict[str, EffectiveValue]): Effective values.
        key (str): Key.
        sub (str | None): Sub-key for range values (``low``/``high``).

    Returns:
        Decimal | None: Value, or None if unresolved or non-numeric.
    """
    ev = eff.get(key)
    if ev is None:
        return None
    v: Any = ev.value[sub] if sub is not None else ev.value
    return Decimal(v) if isinstance(v, (int, Decimal)) else None


def check_risk_rules(eff: dict[str, EffectiveValue], candidates: list[Decimal]) -> list[str]:
    """
    Apply RP-01 to RP-07 to whichever values are resolved.

    Args:
        eff (dict[str, EffectiveValue]): Effective values.
        candidates (list[Decimal]): ``intraday_allocation_cap_pct.candidates_under_test``.

    Returns:
        list[str]: Errors.
    """
    R = E.RISK_PROFILE_CONTRADICTION
    errs: list[str] = []
    total = _num(eff, "risk.allocation.total_exposure_cap_pct")
    low = _num(eff, "risk.allocation.minimum_reserve_pct_range", "low")
    high = _num(eff, "risk.allocation.minimum_reserve_pct_range", "high")
    daily = _num(eff, "risk.limits.daily_loss_limit_pct")
    breaker = _num(eff, "risk.limits.portfolio_drawdown_circuit_breaker_pct")
    rpt = _num(eff, "risk.sizing.risk_per_trade_pct")
    caps = {
        t: _num(eff, f"risk.concentration.{t}_per_asset_cap_pct")
        for t in ("core", "major", "speculative")
    }
    spec_total = _num(eff, "risk.concentration.speculative_total_cap_pct")
    if total is not None and low is not None and total + low > 100:
        errs.append(_err(R, "RP-01", f"exposure {total} + reserve floor {low} > 100"))
    if total is not None:
        for tier, cap in caps.items():
            if cap is not None and cap > total:
                errs.append(_err(R, "RP-02", f"{tier} cap {cap} > total exposure {total}"))
    spec = caps["speculative"]
    if spec is not None and spec_total is not None and spec > spec_total:
        errs.append(_err(R, "RP-03", "speculative per-asset cap > speculative total cap"))
    if spec_total is not None and total is not None and spec_total > total:
        errs.append(_err(R, "RP-03", "speculative total cap > total exposure cap"))
    if daily is not None and breaker is not None and daily >= breaker:
        errs.append(_err(R, "RP-04", f"daily loss {daily} >= breaker {breaker}"))
    if rpt is not None and daily is not None and rpt >= daily:
        errs.append(_err(R, "RP-05", f"risk per trade {rpt} >= daily loss {daily}"))
    if low is not None and high is not None and low > high:
        errs.append(_err(R, "RP-06", f"reserve low {low} > high {high}"))
    intraday = _num(eff, "risk.allocation.intraday_allocation_cap_pct")
    if intraday is not None:
        if total is not None and intraday > total:
            errs.append(_err(R, "RP-07", "intraday cap > total exposure cap"))
        ev = eff["risk.allocation.intraday_allocation_cap_pct"]
        if ev.provenance.value == "approved" and candidates and intraday not in candidates:
            errs.append(_err(R, "RP-07", "approved intraday cap must be a tested candidate"))
    for sleeve_key, prof in (
        ("daily_loss_limit_pct", daily),
        ("drawdown_circuit_breaker_pct", breaker),
    ):
        sv = _num(eff, f"risk.allocation.intraday_sleeve_limits.{sleeve_key}")
        if sv is not None and prof is not None and sv > prof:
            errs.append(_err(R, "RP-07", f"intraday sleeve {sleeve_key} exceeds profile limit"))
    return errs
