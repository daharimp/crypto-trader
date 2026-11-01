"""T-44: a backtest without an experiment set is blocked (fail closed)."""

from __future__ import annotations

import re

from tests.conftest import make_datasets
from tests.e2e.conftest import PROFILE, cli
from trader.journal.store import read_events


def test_t44_blocked_without_experiment() -> None:
    """T-44: exit 3; RUN_BLOCKED with UD IDs; zero ORDER_INTENT_CREATED."""
    ids = make_datasets(days=60)
    res = cli(
        "backtest",
        "run",
        "--profile",
        PROFILE,
        "--datasets",
        ",".join(ids),
        "--strategy",
        "sma_trend",
        "--timeframe",
        "4h",
        expect=3,
    )
    run_id = re.search(r"run_id: (\S+)", res.stdout).group(1)  # type: ignore[union-attr]
    ev = read_events(run_id)
    blocked = [e["payload"] for e in ev if e["event_type"] == "RUN_BLOCKED"]
    assert blocked and {"UD-01", "UD-02", "UD-03", "UD-17", "UD-18"} <= set(
        blocked[0]["unresolved_decisions"]
    )
    assert not [e for e in ev if e["event_type"] == "ORDER_INTENT_CREATED"]


def test_backtest_input_failures(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Failure paths: unknown dataset, missing instrument, bad timeframe, bad strategy."""
    from tests.e2e.conftest import FIXTURE

    ids = make_datasets(days=60)
    base = [
        "backtest",
        "run",
        "--profile",
        PROFILE,
        "--experiment",
        FIXTURE,
        "--strategy",
        "sma_trend",
        "--timeframe",
        "4h",
        "--datasets",
    ]
    cli(*base, "ds-0000000000000000", expect=2)
    cli(*base, ids[0], expect=2)  # ETH missing
    cli(*base[:-3], "--timeframe", "1h", "--datasets", ",".join(ids), expect=2)
    cli(*[a if a != "sma_trend" else "nope" for a in base], ",".join(ids), expect=2)
