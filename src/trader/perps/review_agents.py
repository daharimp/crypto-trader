"""Review assistant (ADR-039): role-based reviewers that explain a paper account's day.

Roles, each a separate Claude request that sees only the deterministic fact pack
(``review_facts``) plus what the pipeline hands it:

1. market analyst, 2. trade reviewer, 3. risk officer: independent, in parallel, facts only;
4. strategy researcher: proposes at most three setting changes (or none);
5. skeptic: challenges each proposal without seeing the researcher's private reasoning;
6. lead editor: writes the plain-language report.

Code, not a model, checks every proposal against the account's own config rules and renders
the proposals table, so a value cannot be misquoted. Nothing here edits a config, places an
order, or changes the running account: the owner decides and edits the file (RUNBOOK 7a).
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trader.profiles.loader import ConfigLoadError, load_yaml

from .params import PerpsConfigFile, PerpsConfigUnresolvedError, resolve
from .review_facts import ACCOUNTS, ADJUSTABLE

KEY_ENV = "ANTHROPIC_API_KEY"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_PROPOSALS = 3
# Reason: the project never states or implies certain profit (CLAUDE.md); a report that does
# is flagged at the top rather than silently shipped.
BANNED = re.compile(
    r"(?<!not )(?<!no )(?<!never )guarantee|risk[- ]free|can'?t lose|cannot lose"
    r"|sure thing|certain profit",
    re.I,
)
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class FreeTradeReviews(BaseModel):
    """
    ADR-049: per-trade reviews on a free OpenRouter model (not risk values).

    Off by default so an older ``assistant.yaml`` keeps working. The key is read only from
    ``OPENROUTER_API_KEY`` on the server; without it the reviews skip quietly.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    base_url: str = Field(default="https://openrouter.ai/api/v1", pattern=r"^https://")
    # Reason: OpenRouter tries these in order, so a busy free model falls back to the next.
    models: list[str] = Field(default_factory=list, max_length=3)
    max_tokens: int = Field(default=4000, ge=512, le=32000)
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    retries: int = Field(default=1, ge=0, le=2)
    # Reason: free accounts get 50 requests a day and failed ones count, so stay under it.
    daily_call_budget: int = Field(default=45, ge=1, le=1000)
    lookback_hours: int = Field(default=24, ge=1, le=72)
    timeout_s: int = Field(default=120, ge=10, le=600)
    # ADR-052: bull and bear arguments from two free models, then a judge's verdict, with a
    # memory of past verdicts checked against what the price did after each exit. Off by
    # default; an empty role list falls back to ``models``.
    debate: bool = False
    bull_models: list[str] = Field(default_factory=list, max_length=3)
    bear_models: list[str] = Field(default_factory=list, max_length=3)
    judge_models: list[str] = Field(default_factory=list, max_length=3)
    memory_reviews: int = Field(default=5, ge=0, le=20)
    follow_up_bars: int = Field(default=6, ge=1, le=48)

    @model_validator(mode="after")
    def _models_when_enabled(self) -> FreeTradeReviews:
        if self.enabled and not self.models:
            raise ValueError("free_trade_reviews.enabled needs at least one model")
        return self

    def models_for(self, role: str) -> list[str]:
        """Models for a debate role (``bull``, ``bear``, ``judge``); ``models`` when unset."""
        chosen = {
            "bull": self.bull_models,
            "bear": self.bear_models,
            "judge": self.judge_models,
        }.get(role)
        return list(chosen or self.models)

    def debate_calls(self) -> int:
        """Most requests one debate can make: bull, bear, judge and the judge's retries."""
        return 3 + self.retries

    def single_calls(self) -> int:
        """Most requests one single-model review can make."""
        return 1 + self.retries


class AssistantSettings(BaseModel):
    """``configs/assistant.yaml``: which model and effort each role uses (not risk values)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    kind: Literal["ReviewAssistant"]
    model: str = Field(min_length=1)
    max_tokens: int = Field(ge=1024, le=64000)
    effort: dict[str, Effort]
    review_on_bad_day: bool
    accounts: list[Literal["main", "degen", "spot-perps"]]
    # ADR-045: per-trade analysis, a daily summary and drawdown alerts for every account.
    # Defaults keep an older assistant.yaml valid; they are alert settings, not risk values.
    review_every_trade: bool = False
    daily_summary: bool = False
    report_accounts: list[Literal["main", "degen", "spot-perps", "spot"]] = Field(
        default_factory=list
    )
    drawdown_alert_pct: list[float] = Field(default_factory=list)
    # ADR-048: False turns off every Anthropic API call on the server (bad-day reviews, the
    # daily summary and trade reviews); drawdown alerts are code only and keep running. The
    # daily scheduled review on the owner's Claude plan writes the summaries instead.
    server_ai_reviews: bool = True
    free_trade_reviews: FreeTradeReviews = Field(default_factory=FreeTradeReviews)

    def effort_for(self, role: str) -> Effort:
        """Effort for a role (``default`` when the role has none)."""
        return self.effort.get(role, self.effort.get("default", "medium"))


def load_assistant_settings(configs_root: Path) -> AssistantSettings:
    """
    Load ``configs/assistant.yaml``.

    Args:
        configs_root (Path): Config directory.

    Returns:
        AssistantSettings: Settings.
    """
    return AssistantSettings.model_validate(load_yaml(configs_root / "assistant.yaml"))


# --- structured outputs -------------------------------------------------------------------
class CoinNote(BaseModel):
    market: str
    what_happened: str


class MarketNote(BaseModel):
    summary: str
    by_coin: list[CoinNote]


class TradeNote(BaseModel):
    summary: str
    findings: list[str]
    followed_its_rules: bool


class Concern(BaseModel):
    level: Literal["low", "medium", "high"]
    issue: str


class RiskNote(BaseModel):
    summary: str
    concerns: list[Concern]


class Proposal(BaseModel):
    setting: Literal[ADJUSTABLE]  # type: ignore[valid-type]
    proposed_value: str
    why: str
    evidence: str
    how_to_test: str


class Proposals(BaseModel):
    no_change_reason: str
    proposals: list[Proposal]


class Verdict(BaseModel):
    proposal_number: int
    verdict: Literal["worth_testing", "needs_more_data", "reject"]
    reason: str


class Verdicts(BaseModel):
    verdicts: list[Verdict]


class Report(BaseModel):
    headline: str
    report_markdown: str


# --- prompts --------------------------------------------------------------------------------
COMMON = (
    "You review a SIMULATED (paper) crypto account (perpetuals or spot) for its owner. The user "
    "message is a JSON fact pack computed by code; use only numbers that appear in it, say so "
    "when a fact is missing, and never invent prices, trades or results. One day is a small "
    "sample. Past results are not a forecast; never promise or imply profit. You cannot change "
    "anything: the owner decides every change. Write plainly for a non-specialist."
)
ROLES = {
    "market_analyst": "Role: market analyst. Explain what BTC, ETH and SOL did on the review day "
    "and over the last week and month, and how that relates to the 30-day trend the rule follows.",
    "trade_reviewer": "Role: trade reviewer. Check what the account did on the review day against "
    "its rule: each open, close, stop, liquidation and refused open, with dollars. Say whether "
    "it followed its own rules.",
    "risk_officer": "Role: risk officer. Assess exposure: position sizes against equity, how "
    "far liquidation and stops are, the day's loss against the daily limit, and anything near a "
    "limit.",
    "strategy_researcher": "Role: strategy researcher. Using the facts and the three notes, "
    f"propose at most {MAX_PROPOSALS} changes to the listed adjustable settings, each with the "
    "evidence and "
    "a paper test that would show whether it helps. Proposing no change is often right after one "
    "day; then leave proposals empty and say why.",
    "skeptic": "Role: skeptic. Challenge each numbered proposal independently: is the evidence "
    "more than one day of noise, could it raise losses or liquidations, would a replay on past "
    "prices be needed first? Give one verdict per proposal.",
    # ADR-045 roles: one request per closed trade, one per daily summary.
    "trade_analyst": "Role: trade analyst. Review ONE closed paper trade. Explain why it most "
    "likely opened (the account's rule and the candles before entry), why it closed (the "
    "journaled exit reason; when none is recorded, say what the candles suggest and that it is "
    "a guess), how the stop-loss and any take-profit steps behaved (was the stop too tight or "
    "too loose given the measured excursions, was profit given back), whether the trade "
    "followed the account's rules, and at most three concrete things to look at. Judge the "
    "decision process, not just the outcome: a losing trade can be a good trade. Keep each "
    "field short.",
    "daily_editor": "Role: daily editor. Summarize one UTC day across every paper account for "
    "the owner: how each account did, which trades stood out and why, drawdown against each "
    "account's peak, patterns across accounts, and at most three things worth watching. "
    "Accounts that did nothing get one line. Do not restate the numbers table; code adds it. "
    "When review_each_trade is true, also return one trade_reviews entry per trade that has "
    "measured facts (same trade_id): why it opened, why it closed (journaled reason; label any "
    "guess), how the stop-loss and take-profit steps behaved given the measured excursions, "
    "whether it followed its rules, a grade of the decision (not the outcome) and at most two "
    "things to look at, each one sentence. Otherwise leave trade_reviews empty.",
    "lead_editor": "Role: lead editor. Write the owner's report in Markdown from the notes, "
    "proposals and verdicts: a one-line headline, what happened, what the bot did, risk, and what "
    "to consider. Do not restate proposal values; a table is added below your text by code. End by "
    "saying nothing changes unless the owner edits the settings file.",
}


class Client(Protocol):
    """The part of ``anthropic.Anthropic`` the pipeline uses (injectable for tests)."""

    @property
    def beta(self) -> Any: ...


def ask(
    client: Client,
    settings: AssistantSettings,
    role: str,
    payload: dict[str, Any],
    out: type[BaseModel],
) -> Any:
    """
    One role's request with a structured answer; None when the model declines.

    Args:
        client (Client): Anthropic client.
        settings (AssistantSettings): Model and effort.
        role (str): Key of ``ROLES``.
        payload (dict[str, Any]): What this role may see.
        out (type[BaseModel]): Answer schema.

    Returns:
        Any: The parsed answer, or None.
    """
    resp = client.beta.messages.parse(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=f"{COMMON}\n\n{ROLES[role]}",
        messages=[{"role": "user", "content": json.dumps(payload, sort_keys=True, default=str)}],
        output_format=out,
        output_config={"effort": settings.effort_for(role)},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        return None
    return getattr(resp, "parsed_output", None)


def check_proposal(p: Proposal, configs_root: Path, account: str) -> str | None:
    """
    Whether a proposal would be a valid setting for this account; the reason if not.

    Builds the account's config with only that value changed and runs the same checks the
    paper session runs (``resolve``). Nothing is written.

    Args:
        p (Proposal): Proposal.
        configs_root (Path): Config directory.
        account (str): A name from ``ACCOUNTS``.

    Returns:
        str | None: None when valid, else why not.
    """
    try:
        value = Decimal(p.proposed_value.strip().rstrip("%x"))
    except InvalidOperation:
        return f"{p.proposed_value!r} is not a number"
    if value <= 0:
        return "must be positive"
    if p.setting.endswith("_pct_of_collateral") and value >= 100:
        return "must be below 100"
    if p.setting == "max_open_positions" and value != value.to_integral_value():
        return "must be a whole number"
    try:
        raw = load_yaml(configs_root / "perps" / ACCOUNTS[account][0])
        entry = dict(
            raw["risk"].get(p.setting)
            or {
                "status": "approved",
                "ref": "proposal",
                "approved_by": "proposal",
                "approved_on": "proposal",
            }
        )
        entry.update(value=str(value), status="approved")
        entry.setdefault("approved_by", "proposal")
        entry.setdefault("approved_on", "proposal")
        raw["risk"][p.setting] = entry
        resolve(PerpsConfigFile.model_validate(raw))
    except (ConfigLoadError, KeyError, ValueError, PerpsConfigUnresolvedError) as exc:
        return f"rejected by the config checks: {exc}"
    return None


@dataclass
class Review:
    """Everything one review produced."""

    account: str
    day: str
    notes: dict[str, Any] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    no_change_reason: str = ""
    headline: str = ""
    markdown: str = ""


def _dump(x: Any) -> Any:
    return x.model_dump() if isinstance(x, BaseModel) else x


def run_review(
    facts: dict[str, Any], client: Client, settings: AssistantSettings, configs_root: Path
) -> Review:
    """
    Run every role on one fact pack and assemble the report.

    Args:
        facts (dict[str, Any]): From ``review_facts.build_facts``.
        client (Client): Anthropic client.
        settings (AssistantSettings): Model and effort per role.
        configs_root (Path): Config directory (proposals are checked against it).

    Returns:
        Review: Notes, checked proposals with verdicts, and the Markdown report.
    """
    account, day = facts["account"], facts["review_day_utc"]
    rv = Review(account, day)
    first: dict[str, type[BaseModel]] = {
        "market_analyst": MarketNote,
        "trade_reviewer": TradeNote,
        "risk_officer": RiskNote,
    }
    # Reason: the three analysts are independent by design, so none can anchor on another.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            r: pool.submit(ask, client, settings, r, {"facts": facts}, m) for r, m in first.items()
        }
        rv.notes = {r: _dump(f.result()) or {"unavailable": "declined"} for r, f in futures.items()}
    plan = ask(
        client, settings, "strategy_researcher", {"facts": facts, "notes": rv.notes}, Proposals
    )
    props: list[Proposal] = list(plan.proposals[:MAX_PROPOSALS]) if plan else []
    rv.no_change_reason = plan.no_change_reason if plan else "the researcher declined to answer"
    verdicts: dict[int, Verdict] = {}
    if props:
        public = [{"number": i + 1, **p.model_dump()} for i, p in enumerate(props)]
        got = ask(client, settings, "skeptic", {"facts": facts, "proposals": public}, Verdicts)
        verdicts = {v.proposal_number: v for v in (got.verdicts if got else [])}
    for i, p in enumerate(props, start=1):
        current = (facts["settings"].get("risk", {}).get(p.setting) or {}).get("value")
        v = verdicts.get(i)
        rv.proposals.append(
            {
                "number": i,
                **p.model_dump(),
                "current_value": current,
                "config_check": check_proposal(p, configs_root, account) or "passes",
                "skeptic": v.verdict if v else "no verdict",
                "skeptic_reason": v.reason if v else "",
            }
        )
    rep = ask(
        client,
        settings,
        "lead_editor",
        {
            "facts": facts,
            "notes": rv.notes,
            "proposals": rv.proposals,
            "no_change_reason": rv.no_change_reason,
        },
        Report,
    )
    rv.headline = rep.headline if rep else f"{account} paper account review for {day}"
    rv.markdown = render(
        rv,
        rep.report_markdown
        if rep
        else "_The lead editor declined to write a summary; the notes are below._",
    )
    return rv


def render(rv: Review, body: str) -> str:
    """
    The final Markdown: the editor's text, then a code-built proposals table and footer.

    Args:
        rv (Review): Review with checked proposals.
        body (str): The lead editor's Markdown.

    Returns:
        str: Report.
    """
    lines = [
        f"# {rv.headline}",
        "",
        f"Account: **{rv.account}** (paper) · day reviewed: {rv.day} UTC",
        "",
    ]
    if BANNED.search(body) or BANNED.search(rv.headline):
        lines += [
            "> **Warning:** this text used profit-promising wording, which the project does "
            "not allow. Treat it with extra caution.",
            "",
        ]
    lines += [
        body.strip(),
        "",
        "## Proposed setting changes (nothing is changed until you decide)",
        "",
    ]
    if not rv.proposals:
        lines += [f"No change proposed: {rv.no_change_reason}", ""]
    else:
        lines += [
            "| # | Setting | Now | Proposed | Config check | Skeptic |",
            "|---|---|---|---|---|---|",
        ]
        for p in rv.proposals:
            lines.append(
                f"| {p['number']} | `{p['setting']}` | {p['current_value'] or 'off'} "
                f"| {p['proposed_value']} "
                f"| {p['config_check']} | {p['skeptic'].replace('_', ' ')} |"
            )
        lines.append("")
        for p in rv.proposals:
            lines += [
                f"**{p['number']}. `{p['setting']}` → {p['proposed_value']}.** {p['why']}",
                f"- Evidence: {p['evidence']}",
                f"- How to test on paper: {p['how_to_test']}",
                f"- Skeptic: {p['skeptic_reason'] or 'no verdict'}",
                "",
            ]
    lines += [
        "---",
        "Simulated money. Written by an AI review assistant from measured facts; it can be wrong. "
        "Past results are not a forecast and profit is not guaranteed. To apply a change, edit the "
        "account's settings file yourself (RUNBOOK 7a).",
    ]
    return "\n".join(lines) + "\n"
