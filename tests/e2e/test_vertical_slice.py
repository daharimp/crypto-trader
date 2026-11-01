"""T-42: end-to-end slice through the CLI."""

from __future__ import annotations

import json
from typing import Any

from tests.e2e.conftest import cli

SECTIONS = [
    "report_schema_version",
    "run_metadata",
    "disclaimer",
    "provenance",
    "data",
    "costs",
    "strategy",
    "benchmarks",
    "comparison",
    "trading",
    "journal",
]


def test_t42_vertical_slice(slice_run: dict[str, Any]) -> None:
    """T-42: exit 0 everywhere; full report; benchmarks; rejections; provenance; logs."""
    run_id = slice_run["run_id"]
    rep = json.loads((slice_run["report_dir"] / "report.json").read_text())
    assert list(rep) == sorted(SECTIONS) or set(SECTIONS) <= set(rep)
    assert set(rep["benchmarks"]) == {"bm_cash", "bm_bh_btc", "bm_bh_eth", "bm_ew_btc_eth"}
    assert {c["benchmark"] for c in rep["comparison"]} == set(rep["benchmarks"])
    assert "rejections_by_reason" in rep["trading"]
    assert rep["trading"]["order_intents"] > 0 and rep["trading"]["fills"] > 0
    for k in ("total_return", "fees_usd", "slippage_cost_usd", "max_drawdown", "closed_trades"):
        assert k in rep["strategy"]["metrics"]
    na = rep["provenance"]["non_approved_values"]
    assert {v["provenance"] for v in na} == {"fixture", "hypothesis"}
    assert rep["provenance"]["experiment_id"] == "EXP-0000-001"
    md = cli("report", "show", run_id).stdout
    assert "Values used that are NOT owner-approved" in md and "Rejections by reason" in md
    assert json.loads(cli("report", "show", run_id, "--format", "json").stdout)["journal"]
    out = cli("journal", "verify", run_id).stdout
    assert out.startswith("OK ") and rep["journal"]["root_hash"] in out
    log = (slice_run["data"] / "logs" / f"{run_id}.jsonl").read_text().splitlines()
    rows = [json.loads(x) for x in log]
    assert all(r["run_id"] == run_id for r in rows)
    assert any(r["correlation_id"] for r in rows)
    exp = slice_run["data"] / "experiments" / "EXP-0000-001" / "runs" / f"{run_id}.json"
    rec = json.loads(exp.read_text())
    assert rec["status"] == "completed" and rec["reproduction"]["command"].startswith("trader ")


def test_cli_profile_commands(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """§10.1 profile commands: exit 3, 2, 0; compile writes JSON."""
    p, x = "configs/profiles/balanced-paper.yaml", "experiments/EXP-2026-001-vertical-slice.yaml"
    out = cli("profile", "validate", p, "--environment", "backtest", expect=3).stdout
    for ud in ("UD-01", "UD-02", "UD-03", "UD-04", "UD-12", "UD-15", "UD-16", "UD-17", "UD-18"):
        assert ud in out
    cli("profile", "validate", p, "--environment", "paper", "--experiment", x, expect=2)
    cli("profile", "validate", p, "--environment", "live", expect=2)
    ok = cli("profile", "validate", p, "--environment", "backtest", "--experiment", x).stdout
    assert "runnable: true" in ok and "[hypothesis]" in ok and "[experiment]" in ok
    dst = tmp_path / "c.json"
    cli("profile", "compile", p, "--experiment", x, "--out", str(dst))
    assert json.loads(dst.read_text())["runnable"] is True
    assert '"runnable": false' in cli("profile", "compile", p, expect=3).stdout


def test_cli_data_edges(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Data CLI: list, CSV import, bad CSV, unknown dataset, naive timestamp."""
    good = tmp_path / "g.csv"
    good.write_text(
        "open_time_utc,open,high,low,close,volume\n"
        "2024-01-01T00:00:00Z,10,11,9,10,1\n2024-01-01T04:00:00Z,10,11,9,10,1\n"
    )
    ds = cli(
        "data",
        "import",
        "--csv",
        str(good),
        "--instrument",
        "BTC-USD",
        "--timeframe",
        "4h",
        "--source-label",
        "g",
    ).stdout.strip()
    assert ds.startswith("ds-") and ds in cli("data", "list").stdout
    bad = tmp_path / "b.csv"
    bad.write_text("open_time_utc,open,high,low,close,volume\n2024-01-01T00:00:00Z,10,9,9,10,1\n")
    cli(
        "data",
        "import",
        "--csv",
        str(bad),
        "--instrument",
        "BTC-USD",
        "--timeframe",
        "4h",
        "--source-label",
        "b",
        expect=2,
    )
    cli("data", "validate", "ds-0000000000000000", expect=2)
    cli(
        "data",
        "synth",
        "--instrument",
        "BTC-USD",
        "--timeframe",
        "4h",
        "--start",
        "2024-01-01T00:00:00",
        "--end",
        "2024-01-02T00:00:00Z",
        "--seed",
        "1",
        "--start-price",
        "1",
        expect=2,
    )
    cli("report", "show", "run-missing", expect=2)
    cli("journal", "verify", "run-missing", expect=4)


def test_data_fetch_uses_mocked_ccxt(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Optional CCXT provider: public fetch_ohlcv only; mocked, never hits the network."""
    import sys
    import types

    calls = []

    class FakeExchange:
        def __init__(self, cfg):  # type: ignore[no-untyped-def]
            assert "apiKey" not in cfg and "secret" not in cfg

        def fetch_ohlcv(self, symbol, tf, since, limit):  # type: ignore[no-untyped-def]
            calls.append((symbol, tf, since))
            if since >= 1704085200000:
                return []
            return [[1704067200000 + i * 14400000, 10, 11, 9, 10, 1] for i in range(2)]

    monkeypatch.setitem(sys.modules, "ccxt", types.SimpleNamespace(kraken=FakeExchange))
    out = cli(
        "data",
        "fetch",
        "--exchange",
        "kraken",
        "--symbol",
        "BTC/USD",
        "--instrument",
        "BTC-USD",
        "--timeframe",
        "4h",
        "--start",
        "2024-01-01T00:00:00Z",
        "--end",
        "2024-01-01T08:00:00Z",
    ).stdout
    assert out.strip().startswith("ds-") and calls
