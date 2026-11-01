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
    ("live_without_real_money_flag", ["execution", "permitted_environments"], ["backtest", "live"]),
    ("unknown_env", ["execution", "permitted_environments"], ["backtest", "mainnet"]),
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


def test_real_money_requires_live_and_vice_versa() -> None:
    """ADR-023: real_money_enabled is valid only together with the live environment."""
    from pydantic import ValidationError

    from trader.domain.profiles import Execution

    base = {
        "autonomy_mode": "paper_autonomous",
        "per_trade_approval_required": False,
        "instrument_types": ["spot"],
        "leverage_allowed": False,
        "margin_allowed": False,
        "short_selling_allowed": False,
        "withdrawals_allowed": False,
        "transfers_allowed": False,
    }
    Execution(**base, permitted_environments=["backtest", "paper", "live"], real_money_enabled=True)
    Execution(**base, permitted_environments=["backtest", "paper"], real_money_enabled=False)
    for envs, flag in ((["backtest", "live"], False), (["backtest", "paper"], True)):
        with pytest.raises(ValidationError):
            Execution(**base, permitted_environments=envs, real_money_enabled=flag)


def test_live_orders_must_carry_real_funds() -> None:
    """An order intent's funds must be 'real' exactly in the live environment."""
    from pydantic import ValidationError

    from tests.factories import market_intent
    from tests.helpers import T0

    i = market_intent("BTC-USD", T0)
    with pytest.raises(ValidationError):
        i.model_validate(i.model_dump() | {"environment": "live"})
    with pytest.raises(ValidationError):
        i.model_validate(i.model_dump() | {"funds": "real"})
