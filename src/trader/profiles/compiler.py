"""Profile compiler (§7.4): invalid, incomplete, or contradictory config can never run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from trader.common.canonical import to_canonical_obj
from trader.common.hashing import hash_obj
from trader.common.opstore import OperationalStore
from trader.common.paths import configs_root as default_configs_root
from trader.domain.common import VersionRef
from trader.domain.compiled import CompiledProfile, EffectiveValue
from trader.domain.enums import Environment, Provenance, ValidationErrorCode
from trader.domain.experiments import ExperimentDefinition
from trader.domain.profiles import TradingProfile
from trader.domain.risk_profile import RiskProfile
from trader.domain.universe import AssetRegistry, EligibilityRules

from .blockers import find_blockers, iter_param_nodes, required_fields
from .loader import ConfigLoadError, load_yaml
from .overlay import apply_overlay
from .validator import check_intraday, check_risk_rules, check_trading_profile

COMPILER_VERSION = "1.0.0"
E = ValidationErrorCode
# Reason: schema errors touching these sections are safety violations, not typos (T-03).
_SAFETY_ROOTS = {"execution", "global_hard_constraints"}
_SAFETY_LEAVES = {("capital", "funds"), ("objective", "guaranteed_profitability_assumed")}


@dataclass
class CompileBundle:
    """Everything the engine needs from configuration, plus the compiled profile."""

    compiled: CompiledProfile
    profile: TradingProfile | None = None
    risk: RiskProfile | None = None
    registry: AssetRegistry | None = None
    eligibility: EligibilityRules | None = None
    experiment: ExperimentDefinition | None = None


def _schema_errors(name: str, exc: ValidationError) -> list[str]:
    """
    Translate Pydantic errors into ``SCHEMA_INVALID`` / ``SAFETY_CONSTANT_VIOLATION``.

    Args:
        name (str): Document name for messages.
        exc (ValidationError): Pydantic error.

    Returns:
        list[str]: Error strings.
    """
    out = []
    for e in exc.errors():
        loc = tuple(str(p) for p in e["loc"])
        safety = (loc and loc[0] in _SAFETY_ROOTS) or loc[:2] in _SAFETY_LEAVES
        code = E.SAFETY_CONSTANT_VIOLATION if safety else E.SCHEMA_INVALID
        out.append(f"{code.value}: {name}.{'.'.join(loc)}: {e['msg']}")
    return out


def _parse(model: type[BaseModel], data: Any, name: str, errors: list[str]) -> Any:
    """
    Validate data against a model, appending errors instead of raising.

    Args:
        model (type[BaseModel]): Contract class.
        data (Any): Parsed YAML.
        name (str): Document name.
        errors (list[str]): Error accumulator.

    Returns:
        Any: Model instance or None.
    """
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors.extend(_schema_errors(name, exc))
        return None


def _load(path: Path, errors: list[str], code: ValidationErrorCode = E.SCHEMA_INVALID) -> Any:
    """
    Load YAML, appending an error on failure.

    Args:
        path (Path): File.
        errors (list[str]): Error accumulator.
        code (ValidationErrorCode): Code to use when the file is missing.

    Returns:
        Any: Parsed data or None.
    """
    try:
        return load_yaml(path)
    except ConfigLoadError as exc:
        errors.append(f"{code.value}: {exc}")
        return None


def _base_effective(
    namespace: str, tree: Any, effective: dict[str, EffectiveValue], refs: dict[str, str]
) -> None:
    """
    Add every approved or hypothesis parameter of a parsed model to ``effective``.

    Args:
        namespace (str): ``risk`` or ``eligibility``.
        tree (Any): Parsed model (RiskProfile or EligibilityCriteria).
        effective (dict[str, EffectiveValue]): Accumulator.
        refs (dict[str, str]): Collects the decision ref of every parameter.
    """
    raw = tree.model_dump(mode="python")
    for path, node in iter_param_nodes(raw):
        key = f"{namespace}.{path}"
        refs[key] = node["ref"]
        if node["status"] in ("approved", "hypothesis"):
            obj: Any = tree
            for part in path.split("."):
                obj = getattr(obj, part)
            effective[key] = EffectiveValue(
                field=key,
                value=obj.resolved_value(),
                provenance=Provenance(node["status"]),
                ref=node["ref"],
                source=None,
            )


def compile_bundle(
    profile_path: Path,
    environment: Environment,
    experiment_path: Path | None = None,
    configs_root: Path | None = None,
    cost_scenario: str | None = None,
    store: OperationalStore | None = None,
) -> CompileBundle:
    """
    Compile a TradingProfile for an environment (algorithm §7.4 steps 1-9).

    Args:
        profile_path (Path): TradingProfile YAML.
        environment (Environment): ``backtest`` or ``paper``.
        experiment_path (Path | None): Optional ExperimentDefinition (backtest only).
        configs_root (Path | None): Directory with ``risk/``, ``universe/``, ``costs/``.
            Defaults to ``TRADER_CONFIGS_DIR`` or ``configs``.
        cost_scenario (str | None): Cost scenario ID; defaults to the experiment's, else base.
        store (OperationalStore | None): Store for PV-10; defaults to ``data/state``.

    Returns:
        CompileBundle: Compiled profile and parsed inputs.
    """
    configs_root = configs_root or default_configs_root()
    errors: list[str] = []
    effective: dict[str, EffectiveValue] = {}
    refs: dict[str, str] = {}
    hashes: dict[str, str | None] = {"tp": "", "rp": "", "el": "", "ar": "", "exp": None}

    raw_tp = _load(profile_path, errors)
    profile: TradingProfile | None = _parse(TradingProfile, raw_tp, "profile", errors)
    if raw_tp is not None:
        hashes["tp"] = hash_obj(raw_tp)
    if profile is not None:
        errors.extend(check_trading_profile(profile, environment))
        prior = (store or OperationalStore()).check_and_record_profile(
            profile.profile_id, profile.version, str(hashes["tp"]), datetime.now(UTC)
        )
        if prior is not None:
            errors.append(
                f"{E.PROFILE_VERSION_NOT_INCREMENTED.value} [PV-10]: {profile.profile_id} "
                f"v{profile.version} was compiled with different content; increment version"
            )

    risk: RiskProfile | None = None
    if profile is not None:
        rs = profile.risk_selection
        rp_path = configs_root / "risk" / f"{rs.risk_profile_id}.yaml"
        raw_rp = _load(rp_path, errors, E.RISK_PROFILE_NOT_FOUND)
        risk = _parse(RiskProfile, raw_rp, "risk_profile", errors) if raw_rp else None
        if raw_rp is not None:
            hashes["rp"] = hash_obj(raw_rp)
        if risk is not None and risk.version != rs.risk_profile_version:
            errors.append(
                f"{E.RISK_PROFILE_NOT_FOUND.value} [PV-04]: {rs.risk_profile_id} version "
                f"{risk.version} != requested {rs.risk_profile_version}"
            )
            risk = None
        if risk is not None:
            errors.extend(check_intraday(profile, risk))
            _base_effective("risk", risk, effective, refs)

    raw_el = _load(configs_root / "universe" / "eligibility.yaml", errors)
    elig: EligibilityRules | None = _parse(EligibilityRules, raw_el, "eligibility", errors)
    raw_ar = _load(configs_root / "universe" / "assets.yaml", errors)
    registry: AssetRegistry | None = _parse(AssetRegistry, raw_ar, "assets", errors)
    hashes["el"] = hash_obj(raw_el) if raw_el is not None else ""
    hashes["ar"] = hash_obj(raw_ar) if raw_ar is not None else ""
    if elig is not None:
        _base_effective("eligibility", elig.criteria, effective, refs)

    experiment: ExperimentDefinition | None = None
    if experiment_path is not None:
        experiment = _apply_experiment(
            experiment_path, environment, risk, elig, effective, errors, hashes
        )

    scenario_id = cost_scenario or (experiment.cost_scenario if experiment else "base")
    raw_cost = _load(configs_root / "costs" / f"{scenario_id}.yaml", errors)
    costs = {k: str(v) for k, v in (raw_cost or {}).items() if k not in ("schema_version", "kind")}

    tiers = _tiers_in_scope(profile, registry)
    blockers = find_blockers(required_fields(environment, tiers), effective, refs)
    if environment == Environment.PAPER:
        # Reason: paper accepts only approved or hypothesis provenance (RR-02, §7.4.1).
        for k, ev in effective.items():
            if ev.provenance in (Provenance.EXPERIMENT, Provenance.FIXTURE):
                errors.append(f"{E.EXPERIMENT_PARAMETERS_REJECTED.value}: {k} in paper")
    if risk is not None:
        cands = list(risk.allocation.intraday_allocation_cap_pct.candidates_under_test or [])
        errors.extend(check_risk_rules(effective, cands))

    compiled = _finish(
        environment, profile, risk, experiment, hashes, costs, effective, blockers, errors
    )
    return CompileBundle(compiled, profile, risk, registry, elig, experiment)


def _apply_experiment(
    path: Path,
    environment: Environment,
    risk: RiskProfile | None,
    elig: EligibilityRules | None,
    effective: dict[str, EffectiveValue],
    errors: list[str],
    hashes: dict[str, str | None],
) -> ExperimentDefinition | None:
    """
    Load and apply an experiment parameter set (step 4).

    Args:
        path (Path): Experiment YAML.
        environment (Environment): Requested environment.
        risk (RiskProfile | None): Parsed risk profile.
        elig (EligibilityRules | None): Parsed eligibility rules.
        effective (dict[str, EffectiveValue]): Effective values (updated).
        errors (list[str]): Error accumulator.
        hashes (dict[str, str | None]): Hash accumulator.

    Returns:
        ExperimentDefinition | None: Parsed experiment.
    """
    rej = E.EXPERIMENT_PARAMETERS_REJECTED.value
    if environment == Environment.PAPER:
        errors.append(f"{rej} [R-02]: experiment parameters are refused in paper")
        return None
    raw = _load(path, errors)
    exp: ExperimentDefinition | None = _parse(ExperimentDefinition, raw, "experiment", errors)
    if exp is None:
        return None
    hashes["exp"] = hash_obj(raw)
    is_fixture_path = "fixtures" in path.resolve().parts
    if exp.experiment_id.startswith("EXP-0000-") != is_fixture_path:
        errors.append(f"{rej}: EXP-0000-* IDs are reserved for tests/fixtures")
        return exp
    prov = Provenance.FIXTURE if is_fixture_path else Provenance.EXPERIMENT
    if risk is not None:
        errors.extend(apply_overlay("risk", risk, exp.parameters.risk, prov, effective))
    if elig is not None:
        errors.extend(
            apply_overlay("eligibility", elig.criteria, exp.parameters.eligibility, prov, effective)
        )
    return exp


def _tiers_in_scope(profile: TradingProfile | None, registry: AssetRegistry | None) -> set[str]:
    """
    Return tiers of the in-scope instruments' base assets.

    Args:
        profile (TradingProfile | None): Profile.
        registry (AssetRegistry | None): Asset registry.

    Returns:
        set[str]: Tier names.
    """
    if profile is None or registry is None:
        return set()
    tiers = {a.asset_id: a.tier for a in registry.assets}
    bases = {i.split("-", 1)[0] for i in profile.universe.instruments_in_scope}
    return {tiers[b] for b in bases if b in tiers}


def _finish(
    environment: Environment,
    profile: TradingProfile | None,
    risk: RiskProfile | None,
    experiment: ExperimentDefinition | None,
    hashes: dict[str, str | None],
    costs: dict[str, str],
    effective: dict[str, EffectiveValue],
    blockers: list[Any],
    errors: list[str],
) -> CompiledProfile:
    """
    Assemble the CompiledProfile and its ``config_hash`` (step 8).

    Args:
        environment (Environment): Environment.
        profile (TradingProfile | None): Profile.
        risk (RiskProfile | None): Risk profile.
        experiment (ExperimentDefinition | None): Experiment.
        hashes (dict[str, str | None]): Input hashes.
        costs (dict[str, str]): Cost scenario.
        effective (dict[str, EffectiveValue]): Effective values.
        blockers (list[Any]): Blockers.
        errors (list[str]): Errors.

    Returns:
        CompiledProfile: Final compiled profile.
    """
    fields: dict[str, Any] = {
        "schema_version": "1.0.0",
        "environment": environment,
        "trading_profile": VersionRef(
            id=profile.profile_id if profile else "unknown",
            version=str(profile.version) if profile else "0",
        ),
        "trading_profile_hash": hashes["tp"] or "",
        "risk_profile": VersionRef(
            id=risk.risk_profile_id if risk else "unknown",
            version=str(risk.version) if risk else "0",
        ),
        "risk_profile_hash": hashes["rp"] or "",
        "eligibility_rules_hash": hashes["el"] or "",
        "asset_registry_hash": hashes["ar"] or "",
        "experiment_id": experiment.experiment_id if experiment else None,
        "experiment_hash": hashes["exp"],
        "cost_scenario": costs,
        "effective": dict(sorted(effective.items())),
        "blockers": blockers,
        "errors": errors,
        "runnable": not errors and not blockers,
        "compiler_version": COMPILER_VERSION,
    }
    fields["config_hash"] = hash_obj(to_canonical_obj(fields))
    return CompiledProfile.model_validate(fields)


def compile_profile(
    profile_path: Path,
    environment: Environment,
    experiment_path: Path | None = None,
    configs_root: Path | None = None,
) -> CompiledProfile:
    """
    Compile a profile and return only the CompiledProfile (spec signature, §7.4).

    Args:
        profile_path (Path): TradingProfile YAML.
        environment (Environment): Target environment.
        experiment_path (Path | None): Optional experiment.
        configs_root (Path | None): Configuration root.
            Defaults to ``TRADER_CONFIGS_DIR`` or ``configs``.

    Returns:
        CompiledProfile: Compiled profile.
    """
    return compile_bundle(profile_path, environment, experiment_path, configs_root).compiled


def exit_code(compiled: CompiledProfile) -> int:
    """
    Map a compiled profile to the CLI exit code (step 9).

    Args:
        compiled (CompiledProfile): Compiled profile.

    Returns:
        int: 2 if errors, 3 if blockers, else 0.
    """
    if compiled.errors:
        return 2
    return 3 if compiled.blockers else 0
