"""T-21: benchmarks match hand calculations."""

from __future__ import annotations

from decimal import Decimal

from tests.helpers import T0, candle, hours
from trader.data.frames import candles_to_frame
from trader.data.snapshots import SnapshotBuilder
from trader.domain.market import DatasetManifest, SourceRef
from trader.evaluation.benchmarks import compute_benchmarks
from trader.execution.costs import CostParams

BASE = CostParams("base", Decimal("0.40"), Decimal("10"), Decimal("10"))
STEP = Decimal("0.00000001")


def _builder() -> SnapshotBuilder:
    btc = [
        candle(T0 + hours(4 * i), *p)
        for i, p in enumerate(
            [
                ("100", "105", "95", "100"),
                ("100", "112", "99", "110"),
                ("110", "121", "108", "120"),
                ("120", "125", "100", "105"),
                ("105", "131", "104", "130"),
            ]
        )
    ]
    eth = [
        candle(T0 + hours(4 * i), *p)
        for i, p in enumerate(
            [
                ("10", "11", "9", "10"),
                ("10", "10.5", "9", "9"),
                ("9", "9.5", "8", "8"),
                ("8", "12", "8", "11"),
                ("11", "13", "10", "12"),
            ]
        )
    ]
    b = SnapshotBuilder("4h")
    for inst, c in (("BTC-USD", btc), ("ETH-USD", eth)):
        b.add(
            DatasetManifest(
                schema_version="1.0.0",
                dataset_id=f"ds-{inst}",
                instrument_id=inst,
                timeframe="4h",
                source=SourceRef(provider_id="t", venue_id="sim", retrieved_at_utc=None),
                source_label="t",
                row_count=5,
                first_open_time_utc=c[0].open_time_utc,
                last_open_time_utc=c[-1].open_time_utc,
                content_hash="x",
                parquet_sha256="x",
                quality_status="ok",
                quality_issues=[],
                gaps=[],
            ),
            candles_to_frame(c),
        )
    return b


def test_t21_hand_calculation() -> None:
    """T-21: bh_btc to the cent; cash stays 2500; equal-weight correct."""
    b = _builder()
    times = [T0 + hours(4 * (i + 1)) for i in range(5)]
    bm = compute_benchmarks(b, times, Decimal(2500), BASE, {"BTC-USD": STEP, "ETH-USD": STEP})
    # Buy BTC at bar 1 open 100 * 1.001 = 100.1; qty = floor8(2500 / (100.1 * 1.004)).
    qty = Decimal("24.87552288")
    cost = qty * Decimal("100.1")
    cash = Decimal(2500) - cost - cost * Decimal("0.004")
    assert bm["bm_bh_btc"][-1][1].quantize(Decimal("0.01")) == (cash + qty * 130).quantize(
        Decimal("0.01")
    )
    assert bm["bm_bh_btc"][-1][1].quantize(Decimal("0.01")) == Decimal("3233.82")
    assert [e for _, e in bm["bm_cash"]] == [Decimal(2500)] * 5
    assert bm["bm_bh_btc"][0][1] == Decimal(2500)
    # Equal weight: 1250 each; ETH fill 10 * 1.001 = 10.01.
    q_btc = Decimal("12.43776144")
    q_eth = Decimal("124.37761441")
    spent = sum(
        q * p * Decimal("1.004") for q, p in ((q_btc, Decimal("100.1")), (q_eth, Decimal("10.01")))
    )
    expected = Decimal(2500) - spent + q_btc * 130 + q_eth * 12
    assert bm["bm_ew_btc_eth"][-1][1].quantize(Decimal("0.01")) == expected.quantize(
        Decimal("0.01")
    )


def test_fill_clamped_to_bar_range() -> None:
    """Edge: slippage cannot push the fill outside the bar's high."""
    b = _builder()
    tight = CostParams("x", Decimal("0"), Decimal("1000"), Decimal("10"))  # 10% slippage
    times = [T0 + hours(4 * (i + 1)) for i in range(4)]
    bm = compute_benchmarks(b, times, Decimal(1120), tight, {"BTC-USD": STEP, "ETH-USD": STEP})
    # 100 * 1.10 = 110 clamped to high 112 -> 110 stays; qty = 1120 / 110
    assert bm["bm_bh_btc"][-1][1].quantize(Decimal("0.01")) == (
        Decimal("10.18181818") * 105 + (Decimal(1120) - Decimal("10.18181818") * 110)
    ).quantize(Decimal("0.01"))


def test_empty_window() -> None:
    """Failure/edge: no decision times -> empty curves."""
    bm = compute_benchmarks(_builder(), [], Decimal(2500), BASE, {"BTC-USD": STEP, "ETH-USD": STEP})
    assert all(v == [] for v in bm.values())
