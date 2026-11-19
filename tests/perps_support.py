"""Shared perps test helpers. Values here are TEST FIXTURES with no market meaning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from trader.perps.backtest import Bar
from trader.perps.params import PerpsConfigFile, PerpsParams, resolve

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _v(x: str) -> dict[str, Any]:
    return {
        "value": x,
        "status": "approved",
        "ref": "UD-23",
        "approved_by": "test fixture",
        "approved_on": "2026-11-01",
    }


def fixture_file(**overrides: str) -> dict[str, Any]:
    """A fully approved perps config dict (fixture values), with optional overrides."""
    vals = {
        "open_fee_bps": "6",
        "close_fee_bps": "6",
        "borrow_rate_pct_per_hour": "0.001",
        "maintenance_bps": "20",
        "venue_max_leverage": "100",
        "max_leverage": "5",
        "target_leverage": "3",
        "max_collateral_per_position_pct": "20",
        "max_total_size_pct_of_equity": "150",
        "min_liquidation_distance_pct": "15",
        "max_open_positions": "3",
        "daily_loss_limit_pct": "5",
    }
    vals.update(overrides)
    group = {
        "costs": ("open_fee_bps", "close_fee_bps", "borrow_rate_pct_per_hour"),
        "venue_limits": ("maintenance_bps", "venue_max_leverage"),
    }
    out: dict[str, Any] = {
        "schema_version": "1.0.0",
        "kind": "PerpsConfig",
        "version": 1,
        "venue": "jupiter_perps",
        "mode": "paper",
        "starting_collateral_usd": _v("1000"),
        "markets": [
            {"market": "SOL", "price_mint": "So11111111111111111111111111111111111111112"},
            {"market": "ETH", "price_mint": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs"},
        ],
        "costs": {},
        "venue_limits": {},
        "risk": {},
    }
    for k, v in vals.items():
        g = next((g for g, ks in group.items() if k in ks), "risk")
        out[g][k] = _v(v)
    return out


def fixture_params(**overrides: str) -> PerpsParams:
    """Resolved fixture parameters."""
    return resolve(PerpsConfigFile.model_validate(fixture_file(**overrides)))


def bars_from_closes(closes: list[float], start: datetime = T0, wick: float = 0.002) -> list[Bar]:
    """4h bars whose open is the previous close and whose wicks are +/- ``wick``."""
    out: list[Bar] = []
    prev = Decimal(str(closes[0]))
    for i, c in enumerate(closes):
        cd = Decimal(str(c))
        hi = max(prev, cd) * Decimal(str(1 + wick))
        lo = min(prev, cd) * Decimal(str(1 - wick))
        out.append(Bar(start + timedelta(hours=4 * i), prev, hi, lo, cd))
        prev = cd
    return out
