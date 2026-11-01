"""T-41: re-running a cycle on the same state creates no duplicate orders."""

from __future__ import annotations

from tests.factories import make_state
from tests.helpers import series
from trader.journal.store import read_events
from trader.pipeline.cycle import run_cycle


def test_t41_rerun_cycle_records_duplicate() -> None:
    """T-41: the second run of the same cycle yields DUPLICATE_ORDER and no new intent."""
    closes = [100] * 230 + [90] * 10 + [130] * 12  # > 30 days for eligibility
    btc = series(closes, volume="100000")
    eth = series([100] * len(closes), volume="100000")
    state = make_state({"BTC-USD": btc, "ETH-USD": eth}, run_id="run-t41")
    cross = None
    for bar in btc[200:]:
        run_cycle(state, bar.close_time_utc)
        if state.counts["order_intents"]:
            cross = bar.close_time_utc
            break
    assert cross is not None and state.counts["order_intents"] == 1
    run_cycle(state, cross)  # same cycle, same state
    assert state.counts["order_intents"] == 1
    risk = [e["payload"] for e in read_events("run-t41") if e["event_type"] == "RISK_EVALUATED"]
    assert risk[-1]["reason_codes"] == ["DUPLICATE_ORDER"]
