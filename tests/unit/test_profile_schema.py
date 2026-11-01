"""T-02: schema-invalid profiles are rejected; shipped configs match the JSON Schemas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tests.conftest import ROOT, dump, load
from trader.domain.enums import Environment
from trader.profiles.compiler import compile_profile, exit_code


def _schema(name: str) -> dict[str, Any]:
    return load(ROOT / "schemas" / f"{name}.schema.yaml")


def test_shipped_profile_matches_json_schema() -> None:
    """Expected: the shipped profile validates against Document 1."""
    jsonschema.Draft202012Validator(_schema("trading-profile")).validate(
        load(ROOT / "configs/profiles/balanced-paper.yaml")
    )


@pytest.mark.parametrize("name", ["conservative", "balanced", "aggressive"])
def test_shipped_risk_profiles_match_json_schema(name: str) -> None:
    """Expected: each shipped risk profile validates against its schema."""
    jsonschema.Draft202012Validator(_schema("risk-profile")).validate(
        load(ROOT / "configs" / "risk" / f"{name}.yaml")
    )


def _mutations() -> list[tuple[str, Any]]:
    def missing_status(d: dict[str, Any]) -> None:
        del d["status"]

    def wrong_type(d: dict[str, Any]) -> None:
        d["version"] = "one"

    def unknown_key(d: dict[str, Any]) -> None:
        d["execution"]["turbo_mode"] = True

    def unknown_top(d: dict[str, Any]) -> None:
        d["surprise"] = 1

    return [
        ("missing_status", missing_status),
        ("wrong_type", wrong_type),
        ("unknown_nested", unknown_key),
        ("unknown_top", unknown_top),
    ]


@pytest.mark.parametrize(("label", "mutate"), _mutations())
def test_t02_invalid_profiles_rejected(
    label: str, mutate: Any, profile_data: dict[str, Any], tmp_path: Path
) -> None:
    """T-02: SCHEMA_INVALID (or SAFETY for execution keys); exit 2; JSON Schema agrees."""
    mutate(profile_data)
    path = dump(tmp_path / f"{label}.yaml", profile_data)
    c = compile_profile(path, Environment.BACKTEST)
    assert exit_code(c) == 2 and not c.runnable
    assert any(e.startswith(("SCHEMA_INVALID", "SAFETY_CONSTANT_VIOLATION")) for e in c.errors)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema("trading-profile")).validate(profile_data)


def test_t02_missing_status_is_schema_invalid(profile_data: dict[str, Any], tmp_path: Path) -> None:
    """T-02: a missing top-level field is SCHEMA_INVALID specifically."""
    del profile_data["status"]
    c = compile_profile(dump(tmp_path / "p.yaml", profile_data), Environment.BACKTEST)
    assert any(e.startswith("SCHEMA_INVALID") and "status" in e for e in c.errors)


def test_unreadable_profile_is_error(tmp_path: Path) -> None:
    """Failure: a missing profile file exits 2."""
    c = compile_profile(tmp_path / "absent.yaml", Environment.BACKTEST)
    assert exit_code(c) == 2
