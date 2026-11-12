"""Perps configuration fails closed (ADR-025, UD-23)."""

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
    """UD-23 values (v2-v5), UD-25 12x ceiling (v6), UD-26 assessed leverage (v7)."""
    p = load_perps_params(ROOT / "configs")
    assert p.version == 7
    assert (p.open_fee_bps, p.close_fee_bps, p.maintenance_bps) == (
        Decimal(7),
        Decimal(7),
        Decimal(20),
    )
    assert p.borrow_rate_pct_per_hour == Decimal("0.01") and p.venue_max_leverage == Decimal(250)
    assert (p.max_leverage, p.target_leverage) == (Decimal(25), Decimal(12))
    assert p.max_collateral_per_position_pct == Decimal(10)
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


def test_shipped_opening_leverage_is_assessed_and_clears_the_liquidation_rule() -> None:
    """UD-25/UD-26: up to 12x in a calm market, lower in a jumpy one, always 8% clear."""
    from trader.perps.math import PerpSide
    from trader.perps.risk import AccountView, check_open, size_open

    p = load_perps_params(ROOT / "configs")
    assert p.liquidation_buffer_daily_moves == Decimal(4)
    equity = p.starting_collateral_usd
    view = AccountView(equity, equity, equity, frozenset(), Decimal(0), False)
    seen = {}
    for name, move in (("calm", Decimal("0.010")), ("jumpy", Decimal("0.030"))):
        for side in PerpSide:
            proposal = size_open(p, view, "SOL", side, Decimal(100), move)
            decision = check_open(p, view, proposal)
            assert decision.approved, decision.reasons
            assert abs(proposal.liquidation_price - 100) >= p.min_liquidation_distance_pct
            seen[name] = proposal.leverage
    # Calm: 1 / (4 x 1% + 0.27%) is about 23x, so the 12x ceiling applies.
    # Jumpy: 1 / (4 x 3% + 0.27%) is about 8.1x.
    assert seen == {"calm": Decimal(12), "jumpy": Decimal("8.1")}
    # Three positions at the ceiling stay inside the total-size cap (400% of equity).
    assert 3 * 12 * p.max_collateral_per_position_pct <= p.max_total_size_pct_of_equity
    # Unknown volatility: no position (fail closed).
    refused = check_open(p, view, size_open(p, view, "SOL", PerpSide.LONG, Decimal(100)))
    assert not refused.approved and refused.reasons == ["PERP_VOLATILITY_UNAVAILABLE"]


def test_buffer_is_optional_but_must_be_approved_and_positive() -> None:
    from tests.perps_support import fixture_file, fixture_params
    from trader.perps.params import PerpsConfigFile

    assert fixture_params().liquidation_buffer_daily_moves is None
    assert fixture_params(liquidation_buffer_daily_moves="4").liquidation_buffer_daily_moves == 4
    with pytest.raises(ValueError, match="must be positive"):
        fixture_params(liquidation_buffer_daily_moves="0")
    raw = fixture_file()
    raw["risk"]["liquidation_buffer_daily_moves"] = {
        "value": "TBD",
        "status": "unresolved",
        "ref": "UD-26",
    }
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        resolve(PerpsConfigFile.model_validate(raw))
    assert exc.value.keys == ["risk.liquidation_buffer_daily_moves"]
