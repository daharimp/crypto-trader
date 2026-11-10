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


def test_shipped_config_is_fully_approved() -> None:
    """UD-23: owner limits (2026-11-02) and venue values (2026-11-10) approved; v3."""
    p = load_perps_params(ROOT / "configs")
    assert p.version == 3
    assert (p.open_fee_bps, p.close_fee_bps, p.maintenance_bps) == (
        Decimal(7),
        Decimal(7),
        Decimal(20),
    )
    assert p.borrow_rate_pct_per_hour == Decimal("0.0016") and p.venue_max_leverage == Decimal(250)
    assert (p.max_leverage, p.target_leverage) == (Decimal(25), Decimal(10))
    assert p.max_collateral_per_position_pct == Decimal(20)
    assert p.max_total_size_pct_of_equity == Decimal(400)
    assert p.min_liquidation_distance_pct == Decimal(8) and p.max_open_positions == 3
    assert p.daily_loss_limit_pct == Decimal(15) and p.starting_collateral_usd == Decimal(2500)
    assert set(p.markets) == {"SOL", "ETH", "BTC"}


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
