"""Kraken live adapter: client-side safety checks and exchange edge cases (fake client)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.factories import market_intent, stop_intent
from tests.fake_kraken import FakeAuthError, FakeKraken
from tests.session_support import START, SYMBOLS, candles
from trader.domain.enums import Environment, ExecutionStatus, ReasonCode, Side
from trader.execution.adapters.kraken_live import (
    _ALLOWED_PARAMS,
    KrakenLiveAdapter,
    LiveAdapterError,
    userref_for,
)
from trader.session.market_data import KrakenMarketData
from trader.session.preflight import run_preflight

D = Decimal
NOW = START + timedelta(hours=4 * 301, minutes=3)


def _live(intent):  # type: ignore[no-untyped-def]
    return intent.model_validate(
        intent.model_dump() | {"environment": Environment.LIVE, "funds": "real"}
    )


def _adapter(usd: str = "1000", cap: str = "500") -> tuple[KrakenLiveAdapter, FakeKraken]:
    c4, daily = candles()
    fake = FakeKraken(c4, daily, lambda: NOW, usd=D(usd))
    return KrakenLiveAdapter(fake, SYMBOLS, D(cap), D("0.40"), sleep=lambda s: None), fake


def test_market_buy_fills_and_balances() -> None:
    """Expected: accepted, then filled at Kraken; balances map to instrument IDs."""
    ad, fake = _adapter()
    rep = ad.submit_order(_live(market_intent("BTC-USD", NOW, Side.BUY, qty="1")))
    assert rep.status == ExecutionStatus.ACCEPTED
    [(_, fill)] = ad.fill_market_orders({}, NOW)
    assert fill.status == ExecutionStatus.FILLED and fill.filled_quantity == 1
    assert fill.fees_usd > 0 and ad.get_balances()["BTC-USD"] == 1
    assert ad.list_open_orders() == []


@pytest.mark.parametrize(
    ("intent_kw", "code"),
    [
        ({"qty": "0.00001"}, ReasonCode.SIZE_BELOW_MINIMUM),
        ({"qty": "6", "notional": "600"}, ReasonCode.EXCESSIVE_SIZE),
        ({"qty": "1.000000001"}, ReasonCode.EXCESSIVE_SIZE),
    ],
)
def test_client_side_rejections(intent_kw: dict[str, str], code: ReasonCode) -> None:
    """Failure: below Kraken minimum, above the capital cap, finer than the lot step."""
    ad, fake = _adapter()
    rep = ad.submit_order(_live(market_intent("BTC-USD", NOW, Side.BUY, **intent_kw)))
    assert rep.status == ExecutionStatus.REJECTED and rep.reason_code == code
    assert not [c for c in fake.calls if c[0] == "create_order"]


def test_simulated_funds_refused() -> None:
    """Failure: a simulated-funds intent never reaches Kraken."""
    ad, fake = _adapter()
    rep = ad.submit_order(market_intent("BTC-USD", NOW, Side.BUY, qty="1"))
    assert rep.reason_code == ReasonCode.ADAPTER_NOT_ALLOWED and not fake.calls


def test_parameter_allowlist_blocks_margin() -> None:
    """Spot only: leverage/margin parameters cannot be sent."""
    ad, _ = _adapter()
    with pytest.raises(LiveAdapterError, match="leverage"):
        ad._send("BTC/USD", "buy", D(1), {"leverage": 2})
    assert not {"leverage", "margin", "reduce_only", "reduceOnly"} & _ALLOWED_PARAMS


def test_exchange_error_without_order_is_rejected() -> None:
    """An exchange error with no matching userref -> EXCHANGE_ERROR rejection."""
    ad, fake = _adapter()

    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise ConnectionError("down")

    fake.create_order = boom  # type: ignore[method-assign]
    rep = ad.submit_order(_live(market_intent("BTC-USD", NOW, Side.BUY, qty="1")))
    assert rep.reason_code == ReasonCode.EXCHANGE_ERROR and ad.last_error


def test_stop_missing_is_detected() -> None:
    """A protective stop canceled outside the bot is reported in missing_stops."""
    ad, fake = _adapter()
    fake.balances["BTC"] = D(1)
    ad.submit_order(_live(stop_intent("BTC-USD", NOW, "90")))
    oid = next(iter(fake.orders))
    fake.orders[oid]["status"] = "canceled"
    assert ad.trigger_stops({}) == [] and ad.missing_stops == ["stop"]


def test_state_roundtrip_and_userref() -> None:
    """Export/load keeps order mappings; userref is deterministic and int32."""
    ad, fake = _adapter()
    i = _live(market_intent("BTC-USD", NOW, Side.BUY, qty="1"))
    ad.submit_order(i)
    ad2 = KrakenLiveAdapter(fake, SYMBOLS, D(500), D("0.4"), sleep=lambda s: None)
    ad2.load_state(ad.export_state())
    assert ad2.get_order(i.order_intent_id).status == ExecutionStatus.ACCEPTED
    assert userref_for(i) == userref_for(i) and 0 < userref_for(i) < 2**31
    with pytest.raises(LiveAdapterError):
        KrakenLiveAdapter(fake, SYMBOLS, D(0), D("0.4"))


def test_preflight_pass_and_auth_failure() -> None:
    """Preflight passes on a good key and fails clearly on an invalid one; never trades."""
    ad, fake = _adapter()
    checks = run_preflight(ad, KrakenMarketData(fake, SYMBOLS), NOW)
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert all(c[2].get("validate") for c in fake.calls if c[0] == "create_order")
    assert fake.balances == {"USD": D(1000)}

    def denied():  # type: ignore[no-untyped-def]
        raise FakeAuthError("EAPI:Invalid key")

    fake.fetch_balance = denied  # type: ignore[method-assign]
    bad = run_preflight(ad, KrakenMarketData(fake, SYMBOLS), NOW)
    assert any(not c.ok and "lacks permission" in c.detail for c in bad)
