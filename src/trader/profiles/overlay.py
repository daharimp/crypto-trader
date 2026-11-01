"""Experiment parameter overlay (ADR-016, RP-12). Backtest only; never paper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from trader.domain.compiled import EffectiveValue
from trader.domain.enums import Provenance, ValidationErrorCode
from trader.domain.experiments import ExperimentParam
from trader.domain.params import ParamBase

_FORBIDDEN_ROOTS = ("global_hard_constraints", "kill_switch", "halt_and_liquidation")
_REJECT = ValidationErrorCode.EXPERIMENT_PARAMETERS_REJECTED.value


def _resolve_param(model: BaseModel, path: str) -> ParamBase | None:
    """
    Follow a dotted path through a parsed model to a parameter object.

    Args:
        model (BaseModel): Parsed RiskProfile or EligibilityCriteria.
        path (str): Dotted path.

    Returns:
        ParamBase | None: The parameter, or None if the path does not reach one.
    """
    obj: Any = model
    for part in path.split("."):
        if not isinstance(obj, BaseModel) or part not in type(obj).model_fields:
            return None
        obj = getattr(obj, part)
    return obj if isinstance(obj, ParamBase) else None


def validate_experiment_value(param: ParamBase, value: Any) -> Any:
    """
    Validate an experiment value against the parameter's own type constraints.

    Reason: the experiment value must satisfy the risk-profile schema (RP-12). We re-build
    the parameter with a placeholder hypothesis status purely to reuse the type's numeric
    constraints; the placeholder never leaves this function.

    Args:
        param (ParamBase): The target parameter.
        value (Any): Proposed experiment value.

    Returns:
        Any: The resolved value in canonical plain form.

    Raises:
        ValueError: If the value violates the parameter type.
    """
    cls = type(param)
    data: dict[str, Any] = {"status": "hypothesis", "ref": "H-00"}
    if "value" in cls.model_fields:
        data["value"] = value
    elif isinstance(value, dict):
        data.update(value)
    else:
        raise ValueError(f"{cls.__name__} needs a mapping value")
    try:
        checked = cls.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"value violates {cls.__name__}: {exc.errors()[0]['msg']}") from exc
    if checked.is_tbd():
        raise ValueError("experiment value cannot be TBD")
    return checked.resolved_value()


def apply_overlay(
    namespace: str,
    model: BaseModel,
    params: dict[str, ExperimentParam],
    provenance: Provenance,
    effective: dict[str, EffectiveValue],
) -> list[str]:
    """
    Apply experiment values for one namespace into ``effective``.

    Args:
        namespace (str): ``risk`` or ``eligibility``.
        model (BaseModel): Parsed model the paths are relative to.
        params (dict[str, ExperimentParam]): Path -> value and source.
        provenance (Provenance): ``experiment`` or ``fixture``.
        effective (dict[str, EffectiveValue]): Effective values to update in place.

    Returns:
        list[str]: Errors (``EXPERIMENT_PARAMETERS_REJECTED``).
    """
    errors: list[str] = []
    for path, ep in sorted(params.items()):
        key = f"{namespace}.{path}"
        if namespace == "risk" and path.split(".")[0] in _FORBIDDEN_ROOTS:
            errors.append(f"{_REJECT} [RP-12]: {key} is a protected section")
            continue
        param = _resolve_param(model, path)
        if param is None:
            errors.append(f"{_REJECT} [RP-12]: {key} is not an overridable parameter")
            continue
        if param.status not in ("unresolved", "hypothesis"):
            errors.append(f"{_REJECT} [RP-12]: {key} is {param.status}; only owner may change it")
            continue
        try:
            value = validate_experiment_value(param, ep.value)
        except ValueError as exc:
            errors.append(f"{_REJECT} [RP-12]: {key}: {exc}")
            continue
        effective[key] = EffectiveValue(
            field=key, value=value, provenance=provenance, ref=param.ref, source=ep.source
        )
    return errors
