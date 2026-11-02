"""Perps configuration fails closed (ADR-024, UD-23)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.perps_support import fixture_file, fixture_params
from trader.perps.params import (
    RISK_KEYS,
    PerpsConfigFile,
    PerpsConfigUnresolvedError,
    load_perps_params,
    resolve,
)


def test_shipped_config_is_unresolved_and_lists_every_key() -> None:
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        load_perps_params(Path(__file__).resolve().parents[2] / "configs")
    assert exc.value.refs == ["UD-23"]
    for k in RISK_KEYS:
        assert f"risk.{k}" in exc.value.keys
    assert "starting_collateral_usd" in exc.value.keys


def test_fixture_resolves() -> None:
    p = fixture_params()
    assert p.max_leverage == Decimal(5) and p.max_open_positions == 3
    assert set(p.markets) == {"SOL", "ETH"}


def test_single_tbd_blocks_everything() -> None:
    f = fixture_file()
    f["risk"]["max_leverage"] = {"value": "TBD", "status": "unresolved", "ref": "UD-23"}
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        resolve(PerpsConfigFile.model_validate(f))
    assert exc.value.keys == ["risk.max_leverage"]


def test_missing_key_blocks() -> None:
    f = fixture_file()
    del f["risk"]["daily_loss_limit_pct"]
    with pytest.raises(PerpsConfigUnresolvedError):
        resolve(PerpsConfigFile.model_validate(f))


def test_live_mode_is_rejected() -> None:
    f = fixture_file()
    f["mode"] = "live"
    with pytest.raises(ValidationError):
        PerpsConfigFile.model_validate(f)


def test_approved_needs_approver() -> None:
    f = fixture_file()
    del f["risk"]["max_leverage"]["approved_by"]
    with pytest.raises(ValidationError):
        PerpsConfigFile.model_validate(f)


@pytest.mark.parametrize(
    "overrides", [{"max_leverage": "200"}, {"target_leverage": "6"}, {"target_leverage": "0.5"}]
)
def test_inconsistent_leverage_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        fixture_params(**overrides)


def test_fixture_copy_matches_shipped_config() -> None:
    root = Path(__file__).resolve().parents[2]
    shipped = (root / "configs" / "perps" / "jupiter.yaml").read_text()
    assert (
        root / "tests" / "fixtures" / "configs" / "perps" / "jupiter.yaml"
    ).read_text() == shipped


def test_sizing_rounds_down_to_stay_under_cap() -> None:
    from trader.perps.math import PerpSide
    from trader.perps.risk import AccountView, check_open, size_open

    p = fixture_params()
    v = AccountView(
        Decimal("999.28"), Decimal("999.28"), Decimal(1000), frozenset(), Decimal(0), False
    )
    pr = size_open(p, v, "SOL", PerpSide.SHORT, Decimal(100))
    assert pr.collateral_usd == Decimal("199.85")
    assert check_open(p, v, pr).approved
