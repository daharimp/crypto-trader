"""``sma_stance`` 50/200 signal contract, its dashboard line, and the sma_200 feature (ADR-043)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import series
from trader.data.snapshots import SnapshotBuilder
from trader.data.store import DatasetStore
from trader.domain.enums import EnsembleAction, Side
from trader.domain.features import FeatureSet
from trader.domain.market import SourceRef
from trader.domain.regime import RegimeAssessment
from trader.domain.signals import SignalCandidate
from trader.ensemble.passthrough import decide
from trader.features.definitions import FEATURE_WINDOW_BARS
from trader.features.pipeline import compute_features
from trader.regimes.null_classifier import assess
from trader.strategies.base import SignalIds, watch_line
from trader.strategies.registry import StrategyNotFoundError, build_strategy
from trader.strategies.sma_stance import SmaStance
from trader.ui.data import status_snapshot

SRC = SourceRef(provider_id="test", venue_id="sim", retrieved_at_utc=None)


def run(closes: list[int]) -> list[tuple[FeatureSet, list[SignalCandidate], RegimeAssessment]]:
    """Run features -> null regime -> sma_stance at every bar close."""
    candles = series(closes)
    store = DatasetStore()
    m = store.create(candles, "BTC-USD", "4h", SRC, "stance")
    b = SnapshotBuilder("4h")
    b.add(*store.load(m.dataset_id))
    strat = SmaStance()
    out = []
    for i, c in enumerate(candles):
        t = c.close_time_utc
        snap = b.snapshot("BTC-USD", t, f"cyc-{i}", f"snp-{i}")
        fs = compute_features(
            b.window("BTC-USD", t, FEATURE_WINDOW_BARS), "BTC-USD", "4h", t, f"fs-{i}", ["d"]
        )
        rg = assess(snap, fs, f"rg-{i}")
        out.append((fs, strat.generate(snap, fs, rg, SignalIds(f"s{i}", f"c{i}", f"y{i}")), rg))
    return out


def test_buys_on_every_uptrend_bar_and_sells_in_downtrend() -> None:
    """Expected: BUY on each bar while 50 > 200 (not only at the cross), SELL once below."""
    res = run([100] * 200 + [120] * 40 + [60] * 60)
    up = [s for _, s, _ in res[200:240] if s]
    assert up and all(s[0].side == Side.BUY for s in up)
    assert up[0][0].rationale_codes == ["SMA50_ABOVE_SMA200"]
    assert res[-1][1][0].side == Side.SELL
    assert res[-1][1][0].rationale_codes == ["SMA50_BELOW_SMA200"]
    last_up = next(r for r in reversed(res[200:240]) if r[1])
    dec = decide(last_up[1], last_up[2], "flat", [], "e", "c", "y")
    assert dec.action == EnsembleAction.ENTER_LONG


def test_warmup_has_no_signal_and_says_so() -> None:
    """Edge: under 200 bars there is no sma_200, so no signal and a warm-up line."""
    res = run([100 + i for i in range(150)])
    fs, sigs, _ = res[-1]
    assert fs.values["sma_200"] is None and sigs == []
    assert SmaStance().watch(fs, holding=False).startswith("Warming up")


def test_sma_200_feature_matches_mean_of_last_200() -> None:
    """The new feature is the plain mean of the last 200 closes."""
    closes = list(range(100, 350))
    fs, _, _ = run(closes)[-1]
    assert fs.values["sma_200"] == sum(closes[-200:]) / 200


def test_watch_lines_explain_idle_and_holding() -> None:
    """The dashboard line names the trend and why the account is in cash."""
    down = run([200] * 200 + [100] * 60)[-1][0]
    up = run([100] * 200 + [150] * 60)[-1][0]
    s = SmaStance()
    assert "Downtrend" in s.watch(down, holding=False) and "long only" in s.watch(down, False)
    assert s.watch(up, holding=False).startswith("Uptrend")
    assert s.watch(up, holding=True).startswith("Holding")
    assert s.watch(down, holding=True).startswith("Selling")


def test_watch_line_generic_and_stale() -> None:
    """Strategies without watch() get a generic line; late data says so."""

    class Plain:
        strategy_id = "plain"

    assert watch_line(Plain(), None, False, True) == "No plain entry signal this check."
    assert watch_line(SmaStance(), None, False, False).startswith("Waiting for the latest candle")


def test_rejects_unsupported_periods_and_timeframes() -> None:
    """Failure: only 50/200 on 4h is provided."""
    with pytest.raises(ValueError):
        SmaStance(20, 50)
    shipped = Path(__file__).resolve().parents[2] / "configs"
    strat = build_strategy("sma_stance", shipped, timeframe="4h", forward_session=True)
    assert isinstance(strat, SmaStance)
    with pytest.raises(StrategyNotFoundError):
        build_strategy("sma_stance", shipped, timeframe="1h")


def test_status_snapshot_exposes_watch_and_strategy(tmp_path: Path) -> None:
    """The dashboard API carries the per-coin line and the strategy name."""
    st = tmp_path / "state"
    st.mkdir()
    (st / "session-paper-x.json").write_text(
        json.dumps(
            {
                "meta": {"environment": "paper", "strategy": "sma_stance", "equity_usd": "2500"},
                "ledger": {"cash": "2500", "positions": {}, "trades": []},
                "watch": {"SOL-USD": "Downtrend: waits in cash."},
            }
        )
    )
    s = status_snapshot(tmp_path, None)["sessions"][0]
    assert s["strategy"] == "sma_stance" and s["watch"] == {"SOL-USD": "Downtrend: waits in cash."}
