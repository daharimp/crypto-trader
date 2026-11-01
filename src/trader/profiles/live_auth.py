"""Live authorization checks for the ``live`` environment (ADR-023)."""

from __future__ import annotations

from pathlib import Path

from trader.common.hashing import hash_obj
from trader.common.opstore import OperationalStore
from trader.domain.compiled import EffectiveValue
from trader.domain.enums import Provenance, ValidationErrorCode
from trader.domain.live import LiveAuthorization
from trader.domain.profiles import TradingProfile

from .loader import ConfigLoadError, load_yaml

E = ValidationErrorCode


def apply_live_authorization(
    configs_root: Path,
    profile: TradingProfile | None,
    store: OperationalStore,
    effective: dict[str, EffectiveValue],
    refs: dict[str, str],
    errors: list[str],
) -> tuple[LiveAuthorization | None, str | None]:
    """
    Load ``live/authorization.yaml`` and apply its gates.

    Unresolved values (UD-22) become blockers through the required-field set; a missing
    acknowledgement or an insufficient paper track record is an error. No default exists.

    Args:
        configs_root (Path): Configuration root.
        profile (TradingProfile | None): Parsed profile.
        store (OperationalStore): Store holding the paper track record.
        effective (dict[str, EffectiveValue]): Effective values (updated).
        refs (dict[str, str]): Decision refs (updated).
        errors (list[str]): Errors (updated).

    Returns:
        tuple[LiveAuthorization | None, str | None]: Authorization and its content hash.
    """
    path = configs_root / "live" / "authorization.yaml"
    try:
        raw = load_yaml(path)
        auth = LiveAuthorization.model_validate(raw)
    except (ConfigLoadError, ValueError) as exc:
        errors.append(f"{E.LIVE_NOT_AUTHORIZED.value}: {path}: {exc}")
        return None, None
    for key in ("max_capital_usd", "min_paper_cycles_before_live"):
        param = getattr(auth, key)
        refs[f"live.{key}"] = param.ref
        if param.status == "approved":
            effective[f"live.{key}"] = EffectiveValue(
                field=f"live.{key}",
                value=param.resolved_value(),
                provenance=Provenance.APPROVED,
                ref=param.ref,
                source=None,
            )
        elif param.status == "hypothesis":
            errors.append(f"{E.LIVE_NOT_AUTHORIZED.value}: live.{key} must be owner-approved")
    if auth.acknowledgement is None:
        errors.append(
            f"{E.LIVE_NOT_ACKNOWLEDGED.value}: the owner acknowledgement in {path} is missing"
        )
    cycles = auth.min_paper_cycles_before_live
    if profile is not None and cycles.status == "approved" and isinstance(cycles.value, int):
        done = store.paper_cycle_count(profile.profile_id, profile.version)
        if done < cycles.value:
            errors.append(
                f"{E.LIVE_NOT_AUTHORIZED.value}: paper track record {done} cycles < required "
                f"{cycles.value} for {profile.profile_id} v{profile.version}"
            )
    return auth, hash_obj(raw)
