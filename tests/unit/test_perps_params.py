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


ROOT = Path(__file__).resolve().parents[2]


def test_shipped_config_has_owner_limits_but_venue_values_block() -> None:
    """UD-23 (2026-11-02): owner limits approved; venue values still TBD, so exit 3."""
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        load_perps_params(ROOT / "configs")
    assert exc.value.keys == [
        "costs.open_fee_bps",
        "costs.close_fee_bps",
        "costs.borrow_rate_pct_per_hour",
        "venue_limits.maintenance_bps",
        "venue_limits.venue_max_leverage",
    ]
    from trader.perps.params import load_perps_file

    cfg = load_perps_file(ROOT / "configs")
    approved = {k: cfg.risk[k].value for k in RISK_KEYS}
    assert approved == {
        "max_leverage": Decimal(25),
        "target_leverage": Decimal(10),
        "max_collateral_per_position_pct": Decimal(20),
        "max_total_size_pct_of_equity": Decimal(400),
        "min_liquidation_distance_pct": Decimal(8),
        "max_open_positions": Decimal(3),
        "daily_loss_limit_pct": Decimal(15),
    }
    assert cfg.starting_collateral_usd.value == Decimal(2500) and cfg.version == 2
    assert all(cfg.risk[k].approved_by == "owner" for k in RISK_KEYS)


def test_frozen_fixture_config_is_all_tbd() -> None:
    """Mechanism tests use the frozen all-TBD v1 copy, like the M1 fixtures (ADR-022)."""
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        load_perps_params(ROOT / "tests" / "fixtures" / "configs")
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
