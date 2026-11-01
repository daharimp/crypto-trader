"""T-39: every order traces to signal(s), versions, risk decision, config, and snapshot."""

from __future__ import annotations

from tests.conftest import small_run
from trader.journal.store import read_events
from trader.journal.verify import verify


def test_t39_every_order_traceable() -> None:
    """T-39: D-36 traceability for each ORDER_INTENT_CREATED."""
    r = small_run()
    ev = read_events(r.run_id)
    by_type: dict[str, list[dict]] = {}
    for e in ev:
        by_type.setdefault(e["event_type"], []).append(e["payload"])
    cfg = by_type["PROFILE_COMPILED"][0]["config_hash"]
    sigs = {s["signal_id"]: s for s in by_type["SIGNAL_GENERATED"]}
    risks = {x["risk_decision_id"]: x for x in by_type["RISK_EVALUATED"]}
    snaps = {
        (p["snapshot"]["instrument_id"], p["snapshot"]["latest_bar"]["close_time_utc"])
        for p in by_type["FEATURES_COMPUTED"]
        if p["snapshot"]["latest_bar"]
    }
    orders = by_type["ORDER_INTENT_CREATED"]
    assert orders
    for o in orders:
        assert o["signal_ids"] and all(
            sigs[s]["strategy_version"] == "1.0.0" for s in o["signal_ids"]
        )
        assert o["strategy_versions"] == [{"id": "sma_trend", "version": "1.0.0"}]
        assert o["model_versions"] == []
        assert risks[o["risk_decision_id"]]["status"] in ("approved", "modified")
        assert o["config_hash"] == cfg
        assert o["market_data_timestamp_utc"] <= o["decision_time_utc"]
        if o["purpose"] != "protective_stop":
            assert (o["instrument_id"], o["market_data_timestamp_utc"]) in snaps
    assert verify(r.run_id).ok
