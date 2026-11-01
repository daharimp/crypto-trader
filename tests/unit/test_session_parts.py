"""Market data, alerts, and owner requests used by forward sessions."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.fake_kraken import FakeKraken
from tests.session_support import START, SYMBOLS, candles
from trader.common.opstore import OperationalStore
from trader.domain.enums import EventType
from trader.session.alerts import Alerter
from trader.session.market_data import KrakenMarketData, MarketDataError, live_manifest

NOW = START + timedelta(hours=4 * 100, minutes=3)


def test_market_data_drops_forming_candle() -> None:
    """Expected: the candle still forming at retrieval time is dropped (DQ-11)."""
    c4, daily = candles()
    data = KrakenMarketData(FakeKraken(c4, daily, lambda: NOW), SYMBOLS)
    bars = data.candles("BTC-USD", "4h", NOW)
    assert bars[-1].close_time_utc <= NOW and len(bars) == 100
    assert live_manifest("BTC-USD", "4h", bars, NOW).dataset_id.startswith("live-")
    assert abs((data.server_time() - NOW).total_seconds()) < 1


def test_market_data_errors() -> None:
    """Failure: unknown instrument or exchange error -> MarketDataError (stale, no crash)."""
    c4, daily = candles()
    fake = FakeKraken(c4, daily, lambda: NOW)
    data = KrakenMarketData(fake, SYMBOLS)
    with pytest.raises(MarketDataError):
        data.candles("DOGE-USD", "4h", NOW)

    def down(*a, **k):  # type: ignore[no-untyped-def]
        raise ConnectionError("down")

    fake.fetch_ohlcv = down  # type: ignore[method-assign]
    with pytest.raises(MarketDataError):
        data.candles("BTC-USD", "4h", NOW)


@pytest.mark.parametrize(
    ("kind", "needle"), [("ntfy", b"[LIVE]"), ("slack", b'"text"'), ("discord", b'"content"')]
)
def test_alert_formats(kind: str, needle: bytes) -> None:
    """Alerts post in the format each service expects; only critical events are sent."""
    sent = []
    a = Alerter("https://example.invalid/hook", kind, "[LIVE]", post=sent.append)
    a.on_event(EventType.KILL_SWITCH_ENGAGED, {"reason": "drill", "trigger": "manual"})
    a.on_event(EventType.CYCLE_STARTED, {})
    assert len(sent) == 1 and needle in sent[0].data


def test_alert_failures_never_raise() -> None:
    """Edge: delivery errors are swallowed; no URL means no delivery."""

    def broken(req):  # type: ignore[no-untyped-def]
        raise OSError("offline")

    assert Alerter("https://example.invalid", "ntfy", "x", post=broken).send("hi") is False
    assert Alerter(None).send("hi") is False


def test_owner_requests_queue() -> None:
    """Owner requests are queued once and marked handled."""
    s = OperationalStore()
    rid = s.request("flatten", "out", NOW)
    assert s.pending_request("flatten") == (rid, "out") and s.pending_request("x") is None
    s.mark_request_handled(rid, NOW, "done")
    assert s.pending_request("flatten") is None
    _ = Decimal
