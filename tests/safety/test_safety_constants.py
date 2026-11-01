"""T-03: forbidden safety values are rejected (D-02, D-03)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import dump
from trader.domain.enums import Environment
from trader.profiles.compiler import compile_profile, exit_code

CASES: list[tuple[str, list[str], Any]] = [
    ("funds_real", ["capital", "funds"], "real"),
    ("leverage", ["execution", "leverage_allowed"], True),
    ("margin", ["execution", "margin_allowed"], True),
    ("shorting", ["execution", "short_selling_allowed"], True),
    ("withdrawals", ["execution", "withdrawals_allowed"], True),
    ("transfers", ["execution", "transfers_allowed"], True),
    ("real_money", ["execution", "real_money_enabled"], True),
    ("perpetual", ["execution", "instrument_types"], ["perpetual"]),
    ("live_env", ["execution", "permitted_environments"], ["backtest", "live"]),
    ("guaranteed", ["objective", "guaranteed_profitability_assumed"], True),
]


@pytest.mark.parametrize(("label", "path", "value"), CASES)
def test_t03_forbidden_values_rejected(
    label: str, path: list[str], value: Any, profile_data: dict[str, Any], tmp_path: Path
) -> None:
    """T-03: each forbidden value -> SAFETY_CONSTANT_VIOLATION, exit 2."""
    node = profile_data
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    c = compile_profile(dump(tmp_path / f"{label}.yaml", profile_data), Environment.BACKTEST)
    assert exit_code(c) == 2
    assert any(e.startswith("SAFETY_CONSTANT_VIOLATION") for e in c.errors), c.errors


def test_risk_profile_safety_constants_rejected(configs_copy: Path) -> None:
    """T-03: a risk profile that enables leverage is rejected."""
    from tests.conftest import PROFILE, load

    rp = configs_copy / "risk" / "balanced.yaml"
    data = load(rp)
    data["global_hard_constraints"]["leverage_allowed"] = True
    dump(rp, data)
    c = compile_profile(PROFILE, Environment.BACKTEST, configs_root=configs_copy)
    assert exit_code(c) == 2
    assert any("SAFETY_CONSTANT_VIOLATION" in e for e in c.errors)
