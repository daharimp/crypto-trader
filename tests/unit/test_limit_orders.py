"""Post-only limit orders (cost reduction): simulator model, intents, and live refusal."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.factories import BASE_COSTS, decision, make_ctx, market_intent
from tests.helpers import T0, candle
from trader.domain.enums import Environment, ExecutionStatus, OrderType, ReasonCode, Side
from trader.execution.adapters.simulated import SimulatedExecutionAdapter
from trader.execution.costs import CostParams
from trader.risk.engine import RiskEngine

D = Decimal
MAKER = CostParams(
    "base_maker",
    D("0.40"),
    D("10"),
    D("10"),
    order_style="limit",
    maker_fee_rate_pct=D("0.25"),
    limit_offset_bps=D("5"),
)


def _limit(side: Side, price: str, qty: str = "1"):  # type: ignore[no-untyped-def]
    i = market_intent("BTC-USD", T0, side, qty=qty)
    return i.model_validate(
        i.model_dump() | {"order_type": OrderType.LIMIT, "limit_price": D(price)}
    )


def _fill(intent, bar):  # type: ignore[no-untyped-def]
    ad = SimulatedExecutionAdapter(D(10000), MAKER)
    ad.holdings["BTC-USD"] = D(5)
    ad.submit_order(intent)
    [(_, rep)] = ad.fill_market_orders({"BTC-USD": bar}, T0)
    return rep


def test_buy_limit_fills_at_limit_with_maker_fee() -> None:
    """Expected: bar opens above and trades below the limit -> fill at the limit, maker fee."""
    rep = _fill(_limit(Side.BUY, "99.95"), candle(T0, "100", "101", "99", "100"))
    assert rep.status == ExecutionStatus.FILLED and rep.average_fill_price == D("99.95")
    assert rep.fees_usd == D("99.95") * D("0.0025") and rep.slippage_usd == 0
    assert rep.fee_rate_pct == D("0.25")


@pytest.mark.parametrize(
    ("side", "price", "bar", "why"),
    [
        (Side.BUY, "99.95", ("99.90", "101", "99", "100"), "crossed at the open (post-only)"),
        (Side.BUY, "99.95", ("100", "101", "99.95", "100"), "never traded below"),
        (Side.SELL, "100.05", ("100.10", "101", "99", "100"), "crossed at the open"),
        (Side.SELL, "100.05", ("100", "100.05", "99", "100"), "never traded above"),
    ],
)
def test_limit_not_filled_cases(side: Side, price: str, bar: tuple[str, ...], why: str) -> None:
    """Edge: pessimistic model -> expired with LIMIT_NOT_FILLED (not an execution error)."""
    rep = _fill(_limit(side, price), candle(T0, *bar))
    assert rep.status == ExecutionStatus.EXPIRED, why
    assert rep.reason_code == ReasonCode.LIMIT_NOT_FILLED


def test_sell_limit_fills() -> None:
    """Expected: sell limit fills when the bar trades above it."""
    rep = _fill(_limit(Side.SELL, "100.05"), candle(T0, "100", "101", "99", "100"))
    assert rep.status == ExecutionStatus.FILLED and rep.average_fill_price == D("100.05")


def test_engine_builds_limit_intents_and_market_stops() -> None:
    """Limit style -> limit entry 5 bps below the close; the protective stop stays a stop."""
    ctx = make_ctx(costs=MAKER)
    eng = RiskEngine()
    rd = eng.evaluate(decision("BTC-USD", ctx.decision_time), ctx)
    intent = eng.build_order_intent(rd, ctx)
    assert intent is not None and intent.order_type == OrderType.LIMIT
    assert intent.limit_price == D(100) * (1 - D("0.0005"))
    ad = SimulatedExecutionAdapter(D(2500), MAKER)
    ad.submit_order(intent)
    bar = candle(ctx.decision_time, "100", "101", "99", "100")
    [(_, fill)] = ad.fill_market_orders({"BTC-USD": bar}, ctx.decision_time)
    stop = eng.build_protective_stop_intent(intent, fill, rd, ctx)
    assert stop.order_type == OrderType.STOP_MARKET and stop.limit_price is None
    market = eng.build_order_intent(rd, make_ctx(costs=BASE_COSTS))
    assert market is not None and market.order_type == OrderType.MARKET


def test_intent_validation() -> None:
    """Failure: a limit without a price, or a market order with one, is invalid."""
    i = market_intent("BTC-USD", T0)
    with pytest.raises(ValidationError):
        i.model_validate(i.model_dump() | {"order_type": OrderType.LIMIT})
    with pytest.raises(ValidationError):
        i.model_validate(i.model_dump() | {"limit_price": D(1)})


def test_live_refuses_limit_orders(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Fail closed: limit order style is refused for live, at compile time and in the adapter."""
    from tests.fake_kraken import FakeKraken
    from tests.session_support import START, SYMBOLS, candles, configs
    from trader.common.opstore import OperationalStore
    from trader.execution.adapters.kraken_live import KrakenLiveAdapter
    from trader.profiles.compiler import compile_bundle

    root = configs(tmp_path)
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(root))
    c = compile_bundle(
        root / "profiles" / "balanced-paper.yaml",
        Environment.LIVE,
        None,
        root,
        "base_maker",
        OperationalStore(),
        assume_activated=True,
    ).compiled
    assert any("order_style limit is not supported for live" in e for e in c.errors)
    c4, daily = candles()
    ad = KrakenLiveAdapter(FakeKraken(c4, daily, lambda: START), SYMBOLS, D(500), D("0.4"))
    i = _limit(Side.BUY, "100")
    live = i.model_validate(i.model_dump() | {"environment": "live", "funds": "real"})
    assert ad.submit_order(live).reason_code == ReasonCode.ADAPTER_NOT_ALLOWED


def test_preflight_reports_fee_tier() -> None:
    """Preflight shows the account's maker/taker fees (fake: 0.25% / 0.40%)."""
    from datetime import timedelta

    from tests.fake_kraken import FakeKraken
    from tests.session_support import START, SYMBOLS, candles
    from trader.execution.adapters.kraken_live import KrakenLiveAdapter
    from trader.session.market_data import KrakenMarketData
    from trader.session.preflight import run_preflight

    now = START + timedelta(hours=4 * 301, minutes=3)
    c4, daily = candles()
    fake = FakeKraken(c4, daily, lambda: now)
    ad = KrakenLiveAdapter(fake, SYMBOLS, D(500), D("0.4"), sleep=lambda s: None)
    fee = next(
        c
        for c in run_preflight(ad, KrakenMarketData(fake, SYMBOLS), now)
        if c.name == "account fee tier"
    )
    assert "maker 0.250%" in fee.detail and "taker 0.400%" in fee.detail
