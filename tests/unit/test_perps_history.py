"""History of the paper perps session rebuilt from its event log (read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trader.perps.history import read_history, with_history

OPEN_BTC = {
    "at_utc": "2026-01-01T04:00:00+00:00",
    "event": "OPENED",
    "market": "BTC",
    "side": "long",
    "size_usd": "4000",
    "collateral_usd": "800",
    "entry": "90000",
    "leverage": "5",
    "liquidation_price": "73000.00",
    "fee_usd": "2.40",
}
EVENTS: list[dict[str, Any]] = [
    {"at_utc": "2026-01-01T00:00:00+00:00", "event": "ACCOUNT_STARTED", "cash_usd": "10000"},
    OPEN_BTC,
    {
        "at_utc": "2026-01-01T08:00:00+00:00",
        "event": "OPENED",
        "market": "SUI",
        "side": "long",
        "size_usd": "3000",
        "collateral_usd": "300",
        "entry": "3.92",
        "leverage": "10",
        "liquidation_price": "3.57",
    },
    {
        "at_utc": "2026-01-01T12:00:00+00:00",
        "event": "LIQUIDATED",
        "market": "SUI",
        "side": "long",
        "mark": "3.565",
        "collateral_lost_usd": "300",
    },
    {"at_utc": "2026-01-02T00:00:00+00:00", "event": "DAY_ROLLED", "equity_usd": "9750.10"},
    {
        "at_utc": "2026-01-02T04:00:00+00:00",
        "event": "CLOSED",
        "market": "BTC",
        "side": "long",
        "exit": "92000",
        "pnl_usd": "88.89",
        "fees_usd": "3.10",
        "reason": "signal flipped",
    },
]


def _write(path: Path, events: list[dict[str, Any]], tail: str = "") -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events) + tail, encoding="utf-8")
    return path


def test_pairs_opens_with_closes_and_liquidations(tmp_path: Path) -> None:
    h = read_history(_write(tmp_path / "e.jsonl", EVENTS))
    closed, liq = h["trades"]  # newest first
    assert closed["market"] == "BTC" and closed["leverage"] == "5"
    assert closed["entry"] == "90000" and closed["exit"] == "92000"
    assert closed["pnl_usd"] == "85.79"  # after closing and borrow fees
    assert closed["liquidated"] is False and closed["reason"] == "signal flipped"
    assert liq["market"] == "SUI" and liq["liquidated"] is True
    assert liq["pnl_usd"] == "-300" and liq["exit"] == "3.565"
    assert h["open"] == {}
    assert [p["equity_usd"] for p in h["equity"]] == ["10000", "9750.10"]


def test_missing_log_and_torn_lines_do_not_fail(tmp_path: Path) -> None:
    assert read_history(tmp_path / "none.jsonl") == {"trades": [], "equity": [], "open": {}}
    path = _write(tmp_path / "e.jsonl", EVENTS[:2], tail='{"at_utc": "2026-01-0')
    h = read_history(path)
    assert h["trades"] == [] and list(h["open"]) == ["BTC"]


def test_close_without_a_recorded_open_is_still_listed(tmp_path: Path) -> None:
    h = read_history(_write(tmp_path / "e.jsonl", EVENTS[-1:]))
    assert h["trades"][0]["market"] == "BTC" and "entry" not in h["trades"][0]


def test_with_history_extends_only_the_matching_open_position(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", EVENTS[:2])
    pos = {"market": "BTC", "side": "long", "size_usd": "4000", "collateral_usd": "800"}
    out = with_history({"positions": [{**pos, "entry_price": "90000"}]}, path)
    assert out is not None
    assert out["positions"][0]["liquidation_price"] == "73000.00"
    assert out["positions"][0]["leverage"] == "5" and out["trades"] == []
    # A position the log does not describe (different entry) gets no borrowed numbers.
    other = with_history({"positions": [{**pos, "entry_price": "91000"}]}, path)
    assert other is not None and "liquidation_price" not in other["positions"][0]
    assert with_history(None, path) is None
