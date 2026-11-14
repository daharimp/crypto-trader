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
    """UD-23 values (v2-v5), UD-26 assessed leverage (v7), UD-27 25x ceiling (v8)."""
    p = load_perps_params(ROOT / "configs")
    assert p.version == 8
    assert (p.open_fee_bps, p.close_fee_bps, p.maintenance_bps) == (
        Decimal(7),
        Decimal(7),
        Decimal(20),
    )
    assert p.borrow_rate_pct_per_hour == Decimal("0.01") and p.venue_max_leverage == Decimal(250)
    assert (p.max_leverage, p.target_leverage) == (Decimal(25), Decimal(25))
    assert p.max_collateral_per_position_pct == Decimal(10)
    assert p.max_total_size_pct_of_equity == Decimal(400)
    assert p.min_liquidation_distance_pct == Decimal("3.5") and p.max_open_positions == 3
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
    """UD-26/UD-27: up to 25x in a very calm market, lower in a jumpier one, 3.5% clear."""
    from trader.perps.math import PerpSide
    from trader.perps.risk import AccountView, check_open, size_open

    p = load_perps_params(ROOT / "configs")
    assert p.liquidation_buffer_daily_moves == Decimal(4)
    equity = p.starting_collateral_usd
    view = AccountView(equity, equity, equity, frozenset(), Decimal(0), False)
    seen = {}
    moves = {"very calm": "0.005", "calm": "0.010", "today's BTC": "0.020", "jumpy": "0.030"}
    for name, move in ((k, Decimal(v)) for k, v in moves.items()):
        for side in PerpSide:
            proposal = size_open(p, view, "SOL", side, Decimal(100), move)
            decision = check_open(p, view, proposal)
            assert decision.approved, decision.reasons
            assert abs(proposal.liquidation_price - 100) >= p.min_liquidation_distance_pct
            seen[name] = proposal.leverage
    # Leverage is 1 / (4 x daily move + 0.27%), capped at the 25x ceiling.
    assert seen == {
        "very calm": Decimal(25),
        "calm": Decimal("23.4"),
        "today's BTC": Decimal(12),
        "jumpy": Decimal("8.1"),
    }
    # The total-size cap (400% of equity) still applies: one 25x position is 250% of
    # equity, so a second one at 25x is refused.
    big = size_open(p, view, "SOL", PerpSide.LONG, Decimal(100), Decimal("0.005"))
    held = AccountView(
        equity - big.collateral_usd, equity, equity, frozenset({"SOL"}), big.size_usd, False
    )
    second = check_open(
        p, held, size_open(p, held, "ETH", PerpSide.LONG, Decimal(100), Decimal("0.005"))
    )
    assert not second.approved and second.reasons == ["PERP_TOTAL_SIZE_ABOVE_CAP"]
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
