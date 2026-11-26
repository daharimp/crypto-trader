"""Debate-style trade reviews on free models (ADR-052, after TradingAgents' bull/bear debate).

For each closed paper trade one free model argues the trade was run well (bull), another
argues it was run badly (bear), and a third reads both arguments, the measured facts and how
the judge's own past calls on this account turned out, then gives the verdict. The verdict
grades how the trade was run (entry, stop, exit, rules), not its profit: code sets the
outcome quadrant from the grade and the P&L, so "good process, bad luck" is visible.

The arguments are free text (no format to break). The verdict is checked against
``DebateVerdict``; the judge gets one retry with the error. Nothing here edits a setting or
places an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from trader.perps.review_agents import BANNED, COMMON

from .trade_review import TradeAnalysis

if TYPE_CHECKING:
    from .free_review import FreeReviewer

StopCall = Literal["too_tight", "about_right", "too_loose", "unclear"]
ExitCall = Literal["too_early", "about_right", "too_late", "unclear"]
SIDES = ("bull", "bear")

_RULES = (
    "Judge how the trade was RUN, not whether it made money: was the entry what the account's "
    "rule says, was the stop placed sensibly for the measured excursions, were take-profits "
    "and the exit handled well, were the account's rules followed. A losing trade can be a "
    "good trade and a winner can be a bad one. Use only numbers in the facts."
)
ROLES = {
    "bull": "Role: bull advocate. Make the strongest honest case that this trade was run WELL. "
    f"{_RULES} Give at most five short numbered points, each citing a fact. Concede a point "
    "only if the facts leave no room. Plain text, under 250 words.",
    "bear": "Role: bear advocate. Make the strongest honest case that this trade was run "
    f"BADLY. {_RULES} Give at most five short numbered points, each citing a fact. Concede a "
    "point only if the facts leave no room. Plain text, under 250 words.",
    "judge": "Role: judge. You get the facts, the bull and bear arguments (either may be "
    "missing or wrong) and past_reviews: your recent verdicts on this account and whether "
    "their stop and exit calls proved right once code measured what the price did after the "
    f"exit. {_RULES} Weigh each argument against the facts and say which points held. "
    "Discount the kind of call your scorecard shows you often get wrong. grade is the "
    "PROCESS grade; process_scores rate entry, stop placement, exit management and rule "
    "adherence 1 (poor) to 5 (excellent). stop_call: was the stop too_tight, about_right or "
    "too_loose for the measured moves (unclear if no stop was tested). exit_call: did it exit "
    "too_early, about_right or too_late. lesson: one sentence the next review should "
    "remember. Keep every field short.",
}


class ProcessScores(BaseModel):
    """1-5 per part of how the trade was run."""

    entry: int = Field(ge=1, le=5)
    stop_placement: int = Field(ge=1, le=5)
    exit_management: int = Field(ge=1, le=5)
    rule_adherence: int = Field(ge=1, le=5)


class DebateVerdict(TradeAnalysis):
    """The judge's answer: the trade analysis plus process scores, two calls and a lesson."""

    process_scores: ProcessScores
    bull_points_that_held: list[str]
    bear_points_that_held: list[str]
    stop_call: StopCall
    exit_call: ExitCall
    lesson: str


@dataclass
class Debate:
    """One trade's debate: the two arguments, the verdict and the request count."""

    arguments: dict[str, str] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)
    verdict: DebateVerdict | None = None
    skipped: str | None = None
    calls: int = 0


def quadrant(grade: str, pnl: float | None) -> str:
    """
    Outcome quadrant set by code: process grade against result.

    Args:
        grade (str): ``good``, ``acceptable`` or ``poor``.
        pnl (float | None): Net P&L in dollars.

    Returns:
        str: For example ``good process, bad luck``.
    """
    won = pnl is not None and pnl > 0
    if grade == "poor":
        return "poor process, lucky" if won else "poor process, deserved loss"
    return "sound process, good result" if won else "sound process, bad luck"


def run_debate(reviewer: FreeReviewer, facts: dict[str, Any], past: dict[str, Any]) -> Debate:
    """
    Bull, bear, then judge, each a separate free-model request.

    Args:
        reviewer (FreeReviewer): The free-model client (models per role in its settings).
        facts (dict[str, Any]): From ``trade_review.build_trade_facts``.
        past (dict[str, Any]): From ``review_memory.past_for_prompt``.

    Returns:
        Debate: Arguments, verdict (None when the judge gave no valid answer) and calls made.
    """
    cfg, d = reviewer.cfg, Debate()
    pack = {"facts": facts, "past_reviews": past}
    for side in SIDES:
        models = cfg.models_for(side)
        text, model, n, why = reviewer.ask(f"{COMMON}\n\n{ROLES[side]}", pack, models, None)
        d.calls += n
        d.arguments[side] = str(text)[:3000] if text else f"(no argument: {why})"
        d.models[side] = model
    judge_pack = {**pack, "arguments": d.arguments}
    v, model, n, why = reviewer.ask(
        f"{COMMON}\n\n{ROLES['judge']}", judge_pack, cfg.models_for("judge"), DebateVerdict
    )
    d.calls += n
    d.models["judge"] = model
    if isinstance(v, DebateVerdict):
        d.verdict = v
    else:
        d.skipped = why
    return d


def verdict_record(d: Debate, pnl: float | None) -> dict[str, Any]:
    """The verdict as saved and remembered, with the code-set quadrant."""
    assert d.verdict is not None
    return {**d.verdict.model_dump(), "quadrant": quadrant(d.verdict.grade, pnl)}


def render_debate(d: Debate, pnl: float | None) -> str:
    """Markdown added under the trade note: scores, calls, lesson and both arguments."""
    lines: list[str] = []
    if d.verdict is not None:
        v, s = d.verdict, d.verdict.process_scores
        lines += [
            "## How the trade was run (debate verdict)",
            "",
            f"**{quadrant(v.grade, pnl).capitalize()}.** Process scores (1-5): entry "
            f"{s.entry}, stop placement {s.stop_placement}, exit management "
            f"{s.exit_management}, rule adherence {s.rule_adherence}.",
            "",
            f"Stop: {v.stop_call.replace('_', ' ')} · exit: {v.exit_call.replace('_', ' ')} "
            "(checked against what the price did next in `lessons.md`).",
            "",
            f"**Lesson.** {v.lesson}",
            "",
            "**Bull points that held**",
            *[f"- {x}" for x in v.bull_points_that_held or ["none"]],
            "",
            "**Bear points that held**",
            *[f"- {x}" for x in v.bear_points_that_held or ["none"]],
            "",
        ]
    for side in SIDES:
        arg = d.arguments.get(side, "")
        lines += [
            f"<details><summary>{side.capitalize()} argument "
            f"(`{d.models.get(side, '?')}`)</summary>",
            "",
            arg.strip(),
            "",
            "</details>",
            "",
        ]
    text = "\n".join(lines)
    if BANNED.search(text):
        text = "> **Warning:** profit-promising wording below; treat with caution.\n\n" + text
    return text


def debate_payload(d: Debate) -> dict[str, Any]:
    """What the trade's JSON file keeps of the debate."""
    return {"arguments": d.arguments, "models": d.models, "calls": d.calls}
