"""Dashboard data builders (ADR-026). No network: fake fetchers and temp state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.perps_support import fixture_params
from trader.perps.backtest import Bar
from trader.perps.params import PerpsConfigUnresolvedError
from trader.ui.data import (
    MARKETS,
    candles_payload,
    fetch_bars,
    perps_payload,
    status_snapshot,
    watch_payload,
)


def _rows(n: int, start: float = 100.0) -> list[list[float]]:
    out, p = [], start
    for i in range(n):
        q = p * (1.01 if (i // 30) % 2 == 0 else 0.99)
        out.append(
            [1_700_000_000_000 + i * 14_400_000, p, max(p, q) * 1.002, min(p, q) * 0.998, q, 1.0]
        )
        p = q
    return out


def test_fetch_bars_drops_forming_candle_and_rejects_unknown() -> None:
    bars = fetch_bars(lambda s, t: _rows(10), "SOL", "4h")
    assert len(bars) == 9
    with pytest.raises(ValueError):
        fetch_bars(lambda s, t: _rows(10), "DOGE", "4h")
    with pytest.raises(ValueError):
        fetch_bars(lambda s, t: _rows(10), "SOL", "5m")


def test_candles_payload_has_sma_after_warmup() -> None:
    p = candles_payload(fetch_bars(lambda s, t: _rows(80), "SOL", "4h"))
    assert len(p["candles"]) == 79
    assert len(p["sma_fast"]) == 79 - 19 and len(p["sma_slow"]) == 79 - 49
    assert p["candles"][0]["time"] == 1_700_000_000


def test_perps_payload_blocked_lists_keys() -> None:
    def blocked():  # type: ignore[no-untyped-def]
        raise PerpsConfigUnresolvedError(["costs.open_fee_bps"], ["UD-23"])

    out = perps_payload(blocked, "SOL", [])
    assert out == {"blocked": ["costs.open_fee_bps"], "refs": ["UD-23"]}


def test_perps_payload_runs_replay_with_markers() -> None:
    bars = fetch_bars(lambda s, t: _rows(300), "SOL", "4h")
    out = perps_payload(fixture_params, "SOL", bars)
    assert out["trades"] > 0 and "Not a forecast" in out["disclaimer"]
    assert {m["event"] for m in out["markers"]} >= {"OPENED", "CLOSED"}


def test_perps_payload_unknown_market_is_blocked() -> None:
    assert "blocked" in perps_payload(fixture_params, "BTC", [])  # fixture has SOL, ETH only


def test_status_snapshot_reads_sessions_and_survives_bad_files(tmp_path: Path) -> None:
    st = tmp_path / "state"
    st.mkdir()
    (st / "session-paper.json").write_text(
        json.dumps(
            {
                "meta": {
                    "last_t1": "2026-11-10T04:00:00Z",
                    "equity_usd": "2510.5",
                    "stale_cycles": 0,
                },
                "ledger": {
                    "cash": "2000",
                    "positions": {
                        "BTC-USD": {
                            "quantity": "0.01",
                            "avg_entry_price": "74000",
                            "stop_price": "70000",
                        }
                    },
                    "trades": [
                        {
                            "instrument_id": "ETH-USD",
                            "opened_at": "a",
                            "closed_at": "b",
                            "entry_price": "2000",
                            "exit_price": "2100",
                            "pnl_usd": "10.5",
                        }
                    ],
                },
                "controls": {"breaker_open": False},
            }
        )
    )
    (st / "session-broken.json").write_text("{not json")
    out = status_snapshot(tmp_path, None)
    assert out["kill_switch"] is None
    good = next(s for s in out["sessions"] if s["name"] == "session-paper")
    assert good["equity_usd"] == 2510.5 and good["positions"][0]["stop"] == 70000.0
    assert good["trades"][0]["pnl_usd"] == 10.5
    assert next(s for s in out["sessions"] if s["name"] == "session-broken")["error"]


def test_status_snapshot_empty(tmp_path: Path) -> None:
    assert status_snapshot(tmp_path, None) == {
        "kill_switch": None,
        "sessions": [],
        "live_gate": None,
    }


def test_status_snapshot_reports_progress_fields_and_live_gate(tmp_path: Path) -> None:
    st = tmp_path / "state"
    st.mkdir()
    (st / "session-paper.json").write_text(
        json.dumps(
            {
                "meta": {"environment": "paper", "equity_usd": "2504.6"},
                "ledger": {"cash": "1890.12", "fees_usd": "6.41", "positions": {}, "trades": []},
                "ids": {"cyc": 17},
                "loss": {"day_start": "2498.2", "hwm": "2511.0"},
            }
        )
    )
    gate = {"min_paper_cycles": 42, "max_capital_usd": 250, "acknowledged": False}
    out = status_snapshot(tmp_path, None, gate)
    s = out["sessions"][0]
    assert out["live_gate"] == gate
    assert (s["environment"], s["cycles"]) == ("paper", 17)
    assert (s["day_start_usd"], s["high_water_usd"], s["fees_usd"]) == (2498.2, 2511.0, 6.41)


def test_status_snapshot_tolerates_state_without_progress_fields(tmp_path: Path) -> None:
    st = tmp_path / "state"
    st.mkdir()
    (st / "session-old.json").write_text(
        json.dumps({"meta": {}, "ledger": {"cash": "100", "positions": {}, "trades": []}})
    )
    s = status_snapshot(tmp_path, None)["sessions"][0]
    assert s["cycles"] == 0 and s["day_start_usd"] is None and s["fees_usd"] is None


def _bars(n: int) -> list[Bar]:
    return fetch_bars(lambda sym, tf: _rows(n + 1), "BTC", "4h")


def test_markets_cover_the_trading_universe() -> None:
    assert list(MARKETS) == ["BTC", "ETH", "SOL", "XRP", "SUI"]
    assert len(fetch_bars(lambda sym, tf: _rows(10), "SUI", "4h")) == 9


def test_watch_payload_reports_price_change_trend_and_sparkline() -> None:
    bars = _bars(120)
    # Reason: _rows rises for 30 bars then falls for 30; bars 90-119 fall, so fast < slow.
    row = watch_payload({"BTC": bars}, {"BTC": 50.0})[0]
    assert row["market"] == "BTC" and row["price"] == 50.0
    assert row["trend"] == "down"
    assert row["change_24h_pct"] == pytest.approx((50.0 / float(bars[-7].close) - 1) * 100)
    assert len(row["spark"]) == 43 and row["spark"][-1] == 50.0


def test_watch_payload_short_history_has_no_trend_and_uses_last_close() -> None:
    bars = _bars(5)
    row = watch_payload({"ETH": bars}, {})[0]
    assert row["trend"] is None and row["change_24h_pct"] is None
    assert row["price"] == float(bars[-1].close)


def test_watch_payload_skips_markets_without_bars() -> None:
    assert watch_payload({"BTC": [], "SOL": _bars(60)}, {})[0]["market"] == "SOL"
    assert watch_payload({}, {}) == []
