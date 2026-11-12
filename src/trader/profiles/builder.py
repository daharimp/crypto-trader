"""Turn interview answers into a risk profile, a trading profile, and a spec sheet (ADR-024).

Answers are checked against the question bank (options or the spec envelope), rendered from
the shipped templates, compiled in a scratch copy of ``configs/``, and written only if the
compile has no errors. Every value is recorded as approved by the owner who answered.
"""

from __future__ import annotations

import copy
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from trader.common.opstore import OperationalStore
from trader.domain.enums import Environment

from .compiler import compile_bundle, exit_code
from .questions import HEADER_QUESTIONS, PRESETS, Question, questions_for

PROTECTED_IDS = frozenset(PRESETS) | {"balanced-paper"}
TEMPLATE_PROFILE = "balanced-paper"


class BuildError(ValueError):
    """An answer or the resulting configuration is invalid."""


@dataclass
class BuildResult:
    """What the builder wrote (or would write)."""

    profile_path: Path
    risk_path: Path
    spec_path: Path
    errors: list[str] = field(default_factory=list)
    exit_code: int = 0


def runnable_strategies(configs_root: Path) -> list[dict[str, Any]]:
    """
    Strategies a forward session may run (research-only controls excluded).

    Args:
        configs_root (Path): Configuration directory.

    Returns:
        list[dict[str, Any]]: ``{"id", "timeframes"}`` entries.
    """
    from trader.strategies.registry import RESEARCH_ONLY_STATES

    out = []
    for f in sorted((configs_root / "strategies").glob("*.yaml")):
        e = yaml.safe_load(f.read_text())
        if e.get("lifecycle_state") in RESEARCH_ONLY_STATES:
            continue
        out.append({"id": e.get("strategy_id", f.stem), "timeframes": e.get("timeframes", [])})
    return out


def registry_coins(configs_root: Path) -> list[str]:
    """
    Unblocked asset IDs in the registry.

    Args:
        configs_root (Path): Configuration directory.

    Returns:
        list[str]: Asset IDs.
    """
    reg = yaml.safe_load((configs_root / "universe" / "assets.yaml").read_text())
    return [a["asset_id"] for a in reg["assets"] if not a.get("blocked")]


def check_answer(q: Question, value: Any) -> Any:
    """
    Validate one answer against its question.

    Args:
        q (Question): Question.
        value (Any): Answer.

    Returns:
        Any: Normalised answer.

    Raises:
        BuildError: If the answer is not an option and not a permitted custom value.
    """
    if q.kind == "text":
        text = str(value or "").strip()
        if q.min_length and len(text) < q.min_length:
            raise BuildError(f"{q.id}: needs at least {q.min_length} characters")
        if q.pattern and not re.fullmatch(q.pattern, text):
            raise BuildError(f"{q.id}: {text!r} does not match {q.pattern}")
        return text
    if q.kind == "multi":
        allowed = {o.value for o in q.options}
        chosen = list(dict.fromkeys(value or []))
        if not chosen or not set(chosen) <= allowed:
            raise BuildError(f"{q.id}: choose one or more of {sorted(allowed)}")
        return chosen
    if q.kind == "range":
        lo, hi = (Decimal(str(v)) for v in value)
        if [float(lo), float(hi)] in [[float(x) for x in o.value] for o in q.options]:
            return [lo, hi]
        if not (q.custom_min <= float(lo) < float(hi) <= q.custom_max):  # type: ignore[operator]
            raise BuildError(f"{q.id}: need {q.custom_min} <= floor < ceiling <= {q.custom_max}")
        return [lo, hi]
    for o in q.options:
        if o.value == value or str(o.value) == str(value) or o.key == str(value):
            return o.value
    if q.allows_custom:
        try:
            num = Decimal(str(value))
        except Exception as exc:
            raise BuildError(f"{q.id}: {value!r} is not a number") from exc
        if not (q.custom_min <= float(num) <= q.custom_max):  # type: ignore[operator]
            raise BuildError(
                f"{q.id}: {num} is outside the spec's range {q.custom_min}..{q.custom_max}"
            )
        if q.integer and num != num.to_integral_value():
            raise BuildError(f"{q.id}: must be a whole number")
        return int(num) if q.integer else num
    raise BuildError(f"{q.id}: {value!r} is not one of {[o.key for o in q.options]}")


def validate_answers(raw: dict[str, Any], configs_root: Path) -> dict[str, Any]:
    """
    Validate a full answer set.

    Args:
        raw (dict[str, Any]): ``{question_id: answer}`` including header answers.
        configs_root (Path): Configuration directory.

    Returns:
        dict[str, Any]: Normalised answers.

    Raises:
        BuildError: On any missing or invalid answer.
    """
    out: dict[str, Any] = {}
    for q in HEADER_QUESTIONS:
        if q.id not in raw:
            raise BuildError(f"missing answer: {q.id}")
        out[q.id] = check_answer(q, raw[q.id])
    if out["profile_id"] in PROTECTED_IDS:
        raise BuildError(f"profile_id {out['profile_id']!r} is reserved; choose another name")
    strategies = runnable_strategies(configs_root)
    for q in questions_for(out["preset"], strategies, registry_coins(configs_root)):
        if q.id not in raw:
            raise BuildError(f"missing answer: {q.id}")
        out[q.id] = check_answer(q, raw[q.id])
    tfs = next(s["timeframes"] for s in strategies if s["id"] == out["strategy_id"])
    if out["decision_timeframe"] not in tfs:
        raise BuildError(f"{out['strategy_id']} does not support {out['decision_timeframe']}")
    return out


def _approved(value: Any, ref: str, owner: str, day: str, **extra: Any) -> dict[str, Any]:
    """An approved parameter record."""
    return {
        "value": value,
        **extra,
        "status": "approved",
        "ref": ref,
        "approved_by": owner,
        "approved_on": day,
    }


def _num(v: Any) -> Any:
    """Decimal -> int or float for YAML output (exact: values come from short decimal text)."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def render_risk(a: dict[str, Any], template: dict[str, Any], version: int, day: str) -> dict:  # type: ignore[type-arg]
    """
    Risk profile YAML data from answers and the preset's shipped file.

    Args:
        a (dict[str, Any]): Normalised answers.
        template (dict[str, Any]): The preset's ``configs/risk/<preset>.yaml``.
        version (int): Version to write.
        day (str): Approval date (YYYY-MM-DD).

    Returns:
        dict: Risk profile data.
    """
    o = a["owner"]
    r = copy.deepcopy(template)
    r.update(
        risk_profile_id=a["profile_id"],
        version=version,
        display_name=f"{a['profile_id']} (built from {a['preset']})",
    )
    r["description"] = f"Owner-built with trader profile build on {day} (ADR-024)."
    r["selection"] = {"initial_default": False, "explicit_selection_required": True}
    lim, siz, con, alo = r["limits"], r["sizing"], r["concentration"], r["allocation"]
    lim["portfolio_drawdown_circuit_breaker_pct"] = _approved(
        _num(a["breaker_pct"]), "UD-01", o, day
    )
    lim["daily_loss_limit_pct"] = _approved(_num(a["daily_loss_pct"]), "UD-02", o, day)
    siz["risk_per_trade_pct"] = _approved(_num(a["risk_per_trade_pct"]), "UD-03", o, day)
    stop = dict(siz["hard_stop_policy"])
    stop.update(
        atr_multiple=_num(a["stop_atr_multiple"]),
        approved_by=o,
        approved_on=day,
        status="approved",
        ref="UD-16",
    )
    siz["hard_stop_policy"] = stop
    for key, field_name in (
        ("core_cap_pct", "core_per_asset_cap_pct"),
        ("major_cap_pct", "major_per_asset_cap_pct"),
        ("spec_cap_pct", "speculative_per_asset_cap_pct"),
        ("spec_total_pct", "speculative_total_cap_pct"),
    ):
        con[field_name] = _approved(_num(a[key]), "UD-13", o, day)
    alo["total_exposure_cap_pct"] = _approved(_num(a["exposure_pct"]), "UD-12", o, day)
    lo, hi = a["reserve_pct_range"]
    alo["minimum_reserve_pct_range"] = {
        "low": _num(lo),
        "high": _num(hi),
        "status": "approved",
        "ref": "UD-04",
        "approved_by": o,
        "approved_on": day,
    }
    alo["max_open_positions"] = _approved(int(a["max_positions"]), "UD-12", o, day)
    cap = int(a["intraday_cap_pct"])
    sleeve = alo["intraday_sleeve_limits"]
    if cap == 0:
        # Reason: "off" keeps the sleeve unresolved, so PV-05 and RR-12 keep refusing it.
        alo["intraday_allocation_cap_pct"] = {
            "value": "TBD",
            "status": "unresolved",
            "ref": "UD-14",
            "candidates_under_test": [5, 10, 15, 20],
        }
        sleeve["daily_loss_limit_pct"] = {"value": "TBD", "status": "unresolved", "ref": "UD-14"}
        sleeve["drawdown_circuit_breaker_pct"] = {
            "value": "TBD",
            "status": "unresolved",
            "ref": "UD-14",
        }
    else:
        alo["intraday_allocation_cap_pct"] = _approved(
            cap, "UD-14", o, day, candidates_under_test=[5, 10, 15, 20]
        )
        f = Decimal("0.5") if a["intraday_limits"] == "B" else Decimal(1)
        sleeve["daily_loss_limit_pct"] = _approved(
            _num(Decimal(str(a["daily_loss_pct"])) * f), "UD-14", o, day
        )
        sleeve["drawdown_circuit_breaker_pct"] = _approved(
            _num(Decimal(str(a["breaker_pct"])) * f), "UD-14", o, day
        )
    count, hours = a["cooldown"]
    cd = r["cooldown"]["after_consecutive_losing_trades"]
    cd["count"] = _approved(int(count), "UD-17", o, day)
    cd["duration_hours"] = _approved(int(hours), "UD-17", o, day)
    flt = r["data_and_execution_faults"]
    flt["stale_data"]["paper_grace_seconds"] = _approved(
        int(a["stale_grace_seconds"]), "UD-17", o, day
    )
    flt["stale_data"]["escalate_to_kill_switch_after_stale_cycles"] = _approved(
        int(a["stale_cycles"]), "UD-17", o, day
    )
    flt["exchange_errors"]["max_consecutive_errors_before_kill_switch"] = _approved(
        int(a["max_exchange_errors"]), "UD-17", o, day
    )
    flt["clock_skew_tolerance_seconds"] = _approved(int(a["clock_skew_seconds"]), "UD-17", o, day)
    return r


def render_profile(
    a: dict[str, Any], template: dict[str, Any], version: int, risk_version: int, now: datetime
) -> dict:  # type: ignore[type-arg]
    """
    Trading profile YAML data from answers and the shipped ``balanced-paper`` profile.

    Args:
        a (dict[str, Any]): Normalised answers.
        template (dict[str, Any]): Shipped trading profile.
        version (int): Version to write.
        risk_version (int): Version of the matching risk profile.
        now (datetime): Build time (UTC).

    Returns:
        dict: Trading profile data.
    """
    p = copy.deepcopy(template)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    p.update(profile_id=a["profile_id"], version=version, status="active", owner=a["owner"])
    p["description"] = f"Owner-built profile ({a['preset']} options), {now.date()} (ADR-024)."
    p.pop("status_history", None)
    p["capital"]["paper_capital_usd"] = _num(a["paper_capital_usd"])
    p["risk_selection"] = {
        "risk_profile_id": a["profile_id"],
        "risk_profile_version": risk_version,
        "adaptation": "within_selected_profile_bounds",
        "profile_switching": "owner_only",
        "aggressive_acknowledgement": {
            "acknowledged": True,
            "acknowledged_by": a["owner"],
            "acknowledged_at_utc": ts,
            "statement": a["acknowledgement"],
        },
    }
    u = p["universe"]
    core = set(u["core_assets"])
    u["manual_allowlist"] = [e for e in u["manual_allowlist"] if e["asset_id"] in a["coins"]]
    u["instruments_in_scope"] = [f"{c}-USD" for c in a["coins"]]
    missing = [
        c
        for c in a["coins"]
        if c not in core and c not in {e["asset_id"] for e in u["manual_allowlist"]}
    ]
    for c in missing:
        u["manual_allowlist"].append(
            {
                "asset_id": c,
                "nominated_by": a["owner"],
                "nominated_at_utc": ts,
                "note": "profile builder",
            }
        )
    p["trading_spec"] = {
        "strategy_id": a["strategy_id"],
        "decision_timeframe": a["decision_timeframe"],
        "built_with": "profile_builder",
    }
    return p


def render_spec_sheet(a: dict[str, Any], result: BuildResult, compile_lines: list[str]) -> str:
    """
    Human-readable spec sheet for the built profile.

    Args:
        a (dict[str, Any]): Normalised answers.
        result (BuildResult): Paths written.
        compile_lines (list[str]): Compile summary per environment.

    Returns:
        str: Markdown.
    """
    rows = [(k, v) for k, v in a.items() if k not in ("acknowledgement",)]
    table = "\n".join(
        f"| `{k}` | {', '.join(map(str, v)) if isinstance(v, list) else v} |" for k, v in rows
    )
    pid = a["profile_id"]
    return f"""# Trading spec: {pid}

Built with `trader profile build` from the **{a["preset"]}** options. Every value below is
approved by {a["owner"]}. Results are not guaranteed; you can lose money.

| Answer | Value |
|---|---|
{table}

**Acknowledgement:** "{a["acknowledgement"]}"

Files: `{result.profile_path}`, `{result.risk_path}`.

## Compile check

{chr(10).join("- " + line for line in compile_lines)}

## Next steps

```bash
trader profile validate {result.profile_path} -e paper
trader profile activate {result.profile_path} -e paper --reason "start paper for {pid}"
trader session run --profile {result.profile_path} -e paper
```

The session uses strategy `{a["strategy_id"]}` on `{a["decision_timeframe"]}` from this profile
unless `--strategy`/`--timeframe` are given. Live still needs `configs/live/authorization.yaml`,
the paper cycles, preflight, and a live activation (ADR-023).
"""


def _next_version(path: Path, update: bool) -> int:
    """Version for a file: 1 if new; old + 1 with ``update``; refuse silent overwrite."""
    if not path.exists():
        return 1
    if not update:
        raise BuildError(f"{path} exists; pass --update to write a new version")
    return int(yaml.safe_load(path.read_text())["version"]) + 1


def build(
    raw: dict[str, Any],
    configs_root: Path,
    docs_dir: Path,
    *,
    update: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> BuildResult:
    """
    Validate answers, render configs, compile them in a scratch copy, then write.

    Args:
        raw (dict[str, Any]): Answers (``{question_id: value}``).
        configs_root (Path): Configuration directory to write into.
        docs_dir (Path): Where the spec sheet goes.
        update (bool): Allow a new version of an existing profile with the same name.
        dry_run (bool): Compile only; write nothing.
        now (datetime | None): Build time (tests).

    Returns:
        BuildResult: Paths, errors, and the exit code (0 runnable, 2 invalid, 3 blocked).

    Raises:
        BuildError: If an answer is invalid.
    """
    now = now or datetime.now(UTC)
    a = validate_answers(raw, configs_root)
    pid = a["profile_id"]
    res = BuildResult(
        configs_root / "profiles" / f"{pid}.yaml",
        configs_root / "risk" / f"{pid}.yaml",
        docs_dir / f"{pid}-spec.md",
    )
    pv, rv = _next_version(res.profile_path, update), _next_version(res.risk_path, update)
    risk_tpl = yaml.safe_load((configs_root / "risk" / f"{a['preset']}.yaml").read_text())
    prof_tpl = yaml.safe_load((configs_root / "profiles" / f"{TEMPLATE_PROFILE}.yaml").read_text())
    risk = render_risk(a, risk_tpl, rv, now.date().isoformat())
    prof = render_profile(a, prof_tpl, pv, rv, now)
    lines: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "configs"
        shutil.copytree(configs_root, scratch)
        (scratch / "risk" / f"{pid}.yaml").write_text(yaml.safe_dump(risk, sort_keys=False))
        sp = scratch / "profiles" / f"{pid}.yaml"
        sp.write_text(yaml.safe_dump(prof, sort_keys=False))
        # Reason: a scratch store, so a trial compile never records a PV-10 content hash
        # (or anything else) in the real operational store.
        store = OperationalStore(Path(tmp) / "state.sqlite")
        for env in (Environment.BACKTEST, Environment.PAPER):
            c = compile_bundle(sp, env, None, scratch, None, store, assume_activated=True).compiled
            code = exit_code(c)
            refs = sorted({b.ref for b in c.blockers})
            lines.append(
                f"{env.value}: exit {code}; errors {len(c.errors)}; blockers {refs or 'none'}"
            )
            res.errors += [e for e in c.errors if e not in res.errors]
            res.exit_code = max(res.exit_code, code)
    if res.errors or dry_run:
        return res
    res.risk_path.write_text(yaml.safe_dump(risk, sort_keys=False))
    res.profile_path.write_text(yaml.safe_dump(prof, sort_keys=False))
    docs_dir.mkdir(parents=True, exist_ok=True)
    res.spec_path.write_text(render_spec_sheet(a, res, lines))
    return res
