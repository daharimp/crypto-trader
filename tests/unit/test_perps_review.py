"""AI review assistant (ADR-039): fact pack, role pipeline, proposal checks, CLI. No real API.

The client is a fake that records each request and returns canned structured answers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS
from trader.cli.main import app
from trader.perps import review_agents as ra
from trader.perps.review_facts import bad_days, build_facts, read_events

T0 = datetime(2026, 9, 1, tzinfo=UTC)
H4 = timedelta(hours=4)
CLOSES = [100 * 0.995**i for i in range(200)]


def _rows(symbol: str = "BTC/USD", tf: str = "4h") -> list[list[float]]:
    out, prev = [], CLOSES[0]
    for i, c in enumerate(CLOSES):
        ms = int((T0 + i * H4).timestamp() * 1000)
        out.append([ms, prev, max(prev, c) * 1.002, min(prev, c) * 0.998, c, 1.0])
        prev = c
    return out


@pytest.fixture
def account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A main paper account run once on falling fake candles, plus a bad day in its log."""
    import trader.ui.data as ui_data

    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", _rows)
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once"])
    assert r.exit_code == 0, r.output
    day = datetime.now(UTC).date().isoformat()
    with (tmp_path / "logs" / "perps-paper-events.jsonl").open("a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write(
            json.dumps(
                {
                    "at_utc": f"{day}T10:00:00+00:00",
                    "event": "DAY_HALTED",
                    "day": day,
                    "loss_usd": "400",
                    "loss_pct": "16",
                    "limit_pct": "15",
                }
            )
            + "\n"
        )
    return tmp_path


class FakeMessages:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers, self.calls = answers, []

    def parse(self, **kw: Any) -> SimpleNamespace:
        self.calls.append(kw)
        out = self.answers.get(kw["output_format"].__name__)
        if out == "refuse":
            return SimpleNamespace(stop_reason="refusal", parsed_output=None)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=out)


def _client(**over: Any) -> SimpleNamespace:
    answers: dict[str, Any] = {
        "MarketNote": ra.MarketNote(
            summary="All three fell.", by_coin=[ra.CoinNote(market="BTC", what_happened="down")]
        ),
        "TradeNote": ra.TradeNote(
            summary="Shorts held.", findings=["opened 3 shorts"], followed_its_rules=True
        ),
        "RiskNote": ra.RiskNote(
            summary="Moderate.", concerns=[ra.Concern(level="medium", issue="3 positions")]
        ),
        "Proposals": ra.Proposals(
            no_change_reason="",
            proposals=[
                ra.Proposal(
                    setting="liquidation_buffer_daily_moves",
                    proposed_value="5",
                    why="calmer",
                    evidence="day loss",
                    how_to_test="paper week",
                ),
                ra.Proposal(
                    setting="target_leverage",
                    proposed_value="500",
                    why="more",
                    evidence="none",
                    how_to_test="none",
                ),
            ],
        ),
        "Verdicts": ra.Verdicts(
            verdicts=[
                ra.Verdict(proposal_number=1, verdict="needs_more_data", reason="one day"),
                ra.Verdict(proposal_number=2, verdict="reject", reason="liquidations"),
            ]
        ),
        "Report": ra.Report(
            headline="Bad day on falling prices",
            report_markdown="Prices fell; profit is not guaranteed.",
        ),
    }
    answers.update(over)
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(answers)))


def _facts(root: Path) -> dict[str, Any]:
    return build_facts("main", None, root, SHIPPED_CONFIGS, _rows, datetime.now(UTC))


def test_fact_pack_is_measured_and_finds_the_bad_day(account: Path) -> None:
    events = read_events(account / "logs" / "perps-paper-events.jsonl")
    assert bad_days(events) == [datetime.now(UTC).date().isoformat()]
    f = _facts(account)
    assert f["review_day_utc"] == bad_days(events)[0]
    assert f["day"]["bad_day"]["loss_pct"] == "16"
    assert f["settings"]["risk"]["liquidation_buffer_daily_moves"]["value"] == 4
    btc = f["markets"]["BTC"]
    assert btc["trend_side_30d"] == "short" and btc["change_30d_pct"] < 0
    assert (
        btc["typical_daily_move_pct"] >= 0
        and "stop_loss_pct_of_collateral" in f["adjustable_settings"]
    )
    json.dumps(f, default=str)  # serializable


def test_unknown_or_never_run_account_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown account"):
        build_facts("yolo", None, tmp_path, SHIPPED_CONFIGS, _rows, T0)
    with pytest.raises(ValueError, match="has not run"):
        build_facts("degen", None, tmp_path, SHIPPED_CONFIGS, _rows, T0)


def test_pipeline_runs_every_role_checks_proposals_and_renders(account: Path) -> None:
    client = _client()
    settings = ra.load_assistant_settings(SHIPPED_CONFIGS)
    rv = ra.run_review(_facts(account), client, settings, SHIPPED_CONFIGS)
    calls = client.beta.messages.calls
    roles = [c["output_format"].__name__ for c in calls]
    assert sorted(roles[:3]) == ["MarketNote", "RiskNote", "TradeNote"] and roles[3:] == [
        "Proposals",
        "Verdicts",
        "Report",
    ]
    assert all(c["model"] == "claude-opus-5-5" and c["fallbacks"] == "default" for c in calls)
    assert calls[3]["output_config"] == {"effort": "high"} and calls[0]["output_config"] == {
        "effort": "medium"
    }
    analysts = [json.loads(c["messages"][0]["content"]) for c in calls[:3]]
    assert all(set(p) == {"facts"} for p in analysts)  # independent: facts only
    assert "notes" in json.loads(calls[3]["messages"][0]["content"])
    p1, p2 = rv.proposals
    assert (
        p1["config_check"] == "passes"
        and p1["current_value"] == 4
        and p1["skeptic"] == "needs_more_data"
    )
    assert (
        p2["config_check"].startswith("rejected by the config checks") and p2["skeptic"] == "reject"
    )
    md = rv.markdown
    assert (
        md.startswith("# Bad day on falling prices")
        and "| 1 | `liquidation_buffer_daily_moves` | 4 | 5 |" in md
    )
    assert "Warning" not in md  # "not guaranteed" is allowed
    assert "nothing is changed until you decide" in md and "RUNBOOK 7a" in md


def test_declined_roles_and_no_proposals_still_give_a_report(account: Path) -> None:
    client = _client(
        MarketNote="refuse",
        Proposals=ra.Proposals(no_change_reason="one day is noise", proposals=[]),
        Report=ra.Report(headline="Quiet day, guaranteed gains ahead", report_markdown="text"),
    )
    rv = ra.run_review(
        _facts(account), client, ra.load_assistant_settings(SHIPPED_CONFIGS), SHIPPED_CONFIGS
    )
    assert rv.notes["market_analyst"] == {"unavailable": "declined"}
    assert "Verdicts" not in [c["output_format"].__name__ for c in client.beta.messages.calls]
    assert "No change proposed: one day is noise" in rv.markdown
    assert "**Warning:**" in rv.markdown  # profit-promising headline is flagged


@pytest.mark.parametrize(
    ("setting", "value", "why"),
    [
        ("liquidation_buffer_daily_moves", "lots", "not a number"),
        ("stop_loss_pct_of_collateral", "100", "below 100"),
        ("max_open_positions", "2.5", "whole number"),
        ("max_collateral_per_position_pct", "-1", "positive"),
    ],
)
def test_proposal_checks_fail_closed(setting: str, value: str, why: str) -> None:
    p = ra.Proposal(setting=setting, proposed_value=value, why="", evidence="", how_to_test="")
    assert why in (ra.check_proposal(p, SHIPPED_CONFIGS, "main") or "")


def test_cli_needs_a_key_dry_run_is_free_and_show(
    account: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ra.KEY_ENV, raising=False)
    r = CliRunner().invoke(app, ["review", "run"])
    assert r.exit_code == 3 and "REVIEW_ASSISTANT_BLOCKED" in r.output
    r = CliRunner().invoke(app, ["review", "run", "--dry-run"])
    assert r.exit_code == 0 and json.loads(r.output)["account"] == "main"
    assert CliRunner().invoke(app, ["review", "run", "--account", "x"]).exit_code == 2
    r = CliRunner().invoke(app, ["review", "show"])
    assert "no review reports" in r.output


def test_review_once_saves_report_and_watch_picks_only_new_recent_bad_days(account: Path) -> None:
    from trader.cli.review import due_days, review_once

    headline, md = review_once("main", None, _client())
    assert md.exists() and md.with_suffix(".json").exists() and headline.startswith("Bad day")
    r = CliRunner().invoke(app, ["review", "show"])
    assert "Bad day on falling prices" in r.output
    today = datetime.now(UTC).date().isoformat()
    assert due_days("main", set(), today) == [today]
    assert due_days("main", {f"main/{today}"}, today) == []
    later = (datetime.now(UTC) + timedelta(days=5)).date().isoformat()
    assert due_days("main", set(), later) == []  # old bad days are not reviewed again
