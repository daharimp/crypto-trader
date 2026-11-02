"""T-35: simulator fill rules (next-bar open, slippage, fees, clamp, stop gaps, min notional)."""

from __future__ import annotations

from decimal import Decimal

from tests.factories import BASE_COSTS, market_intent, stop_intent
from tests.helpers import T0, candle, hours
from trader.domain.enums import ExecutionStatus, ReasonCode, Side
from trader.execution.adapters.registry import (
    ALLOWED_ADAPTERS,
    AdapterNotAllowedError,
    build_adapter,
)
from trader.execution.adapters.simulated import SimulatedExecutionAdapter

D = Decimal


def _ad() -> SimulatedExecutionAdapter:
    return SimulatedExecutionAdapter(D(10000), BASE_COSTS)


def test_t35_market_fills_with_slippage_and_fees() -> None:
    """T-35: buy = open x 1.001, sell = open x 0.999, fee = 0.40% of notional."""
    ad = _ad()
    ad.submit_order(market_intent("BTC-USD", T0, Side.BUY, qty="2"))
    [(_, buy)] = ad.fill_market_orders({"BTC-USD": candle(T0, "100", "110", "90", "105")}, T0)
    assert buy.average_fill_price == D("100.1") and buy.status == ExecutionStatus.FILLED
    assert buy.fees_usd == D("2") * D("100.1") * D("0.004")
    assert buy.slippage_usd == D("0.1") * 2
    t1 = T0 + hours(4)
    ad.submit_order(market_intent("BTC-USD", t1, Side.SELL, qty="2", oid="o2", key="k2"))
    [(_, sell)] = ad.fill_market_orders({"BTC-USD": candle(t1, "200", "210", "190", "205")}, t1)
    assert sell.average_fill_price == D("199.8")
    assert ad.holdings["BTC-USD"] == 0


def test_t35_clamped_to_range() -> None:
    """T-35: fills clamped to [low, high]."""
    ad = _ad()
    ad.submit_order(market_intent("BTC-USD", T0, Side.BUY, qty="1"))
    [(_, r)] = ad.fill_market_orders({"BTC-USD": candle(T0, "100", "100.05", "99", "100")}, T0)
    assert r.average_fill_price == D("100.05")


def test_t35_stop_gap_fills_at_open() -> None:
    """T-35: a stop gapped through fills at min(stop, open) less slippage."""
    ad = _ad()
    ad.submit_order(market_intent("BTC-USD", T0, Side.BUY, qty="1"))
    ad.fill_market_orders({"BTC-USD": candle(T0, "100", "101", "99", "100")}, T0)
    stop = stop_intent("BTC-USD", T0, "95")
    ad.submit_order(stop)
    t1 = T0 + hours(4)
    assert ad.trigger_stops({"BTC-USD": candle(t1, "99", "100", "96", "97")}) == []
    [(_, r)] = ad.trigger_stops({"BTC-USD": candle(t1, "90", "92", "85", "88")})
    assert r.average_fill_price == D(90) * D("0.999")
    t2 = T0 + hours(8)
    ad2 = _ad()
    ad2.holdings["BTC-USD"] = D(1)
    ad2.submit_order(stop)
    [(_, r2)] = ad2.trigger_stops({"BTC-USD": candle(t2, "98", "99", "94", "96")})
    assert r2.average_fill_price == D(95) * D("0.999")


def test_t35_min_notional_and_expiry() -> None:
    """T-35: below $10 rejected; missing next bar -> expired."""
    ad = _ad()
    rep = ad.submit_order(market_intent("BTC-USD", T0, Side.BUY, qty="0.05"))  # $5
    assert rep.status == ExecutionStatus.REJECTED
    assert rep.reason_code == ReasonCode.SIZE_BELOW_MINIMUM
    ad.submit_order(market_intent("BTC-USD", T0, Side.BUY, qty="1", oid="o9", key="k9"))
    [(_, r)] = ad.fill_market_orders({"BTC-USD": None}, T0)
    assert r.status == ExecutionStatus.EXPIRED and r.reason_code == ReasonCode.INTENT_EXPIRED


def test_cancel_and_open_orders() -> None:
    """Edge: cancel moves an open order to canceled."""
    ad = _ad()
    ad.submit_order(market_intent("BTC-USD", T0, Side.BUY, qty="1"))
    assert len(ad.list_open_orders()) == 1
    assert ad.cancel_order("ord-1").status == ExecutionStatus.CANCELED
    assert ad.list_open_orders() == [] and ad.get_order("ord-1").status == "canceled"


def test_adapter_allowlist() -> None:
    """Only the simulated adapter can be built."""
    assert ALLOWED_ADAPTERS == frozenset({"simulated", "kraken_live"})
    import pytest

    with pytest.raises(AdapterNotAllowedError):
        build_adapter("binance", D(1), BASE_COSTS)
    with pytest.raises(AdapterNotAllowedError, match="only via live session"):
        build_adapter("kraken_live", D(1), BASE_COSTS)
    rep = _ad().submit_order(
        market_intent("BTC-USD", T0).model_construct(
            **{**market_intent("BTC-USD", T0).__dict__, "funds": "real"}
        )
    )
    assert rep.status == ExecutionStatus.REJECTED
