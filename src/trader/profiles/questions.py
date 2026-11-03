"""Question bank for building a trading profile (ADR-024).

One bank serves both the terminal interview (``trader profile build``) and the web form
(``trader profile questions --format json``). Every risk option comes from the spec's own
owner-decision options (``docs/spec/product-requirements.md`` §10, UD-01..UD-17). A custom
value is accepted only inside the envelope of those options across all three presets, so
the builder never invents a value or widens a range the spec did not consider.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PRESETS = ("conservative", "balanced", "aggressive")
Kind = Literal["text", "choice", "multi", "number", "range"]


@dataclass(frozen=True)
class Option:
    """One selectable answer."""

    key: str
    label: str
    value: Any
    pros: str = ""
    cons: str = ""
    recommended: bool = False


@dataclass(frozen=True)
class Question:
    """One interview question."""

    id: str
    section: str
    prompt: str
    why: str
    kind: Kind
    ref: str = ""
    options: tuple[Option, ...] = ()
    custom_min: float | None = None
    custom_max: float | None = None
    pattern: str | None = None
    min_length: int | None = None
    integer: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def allows_custom(self) -> bool:
        """Whether a typed value inside ``[custom_min, custom_max]`` is accepted."""
        return self.custom_min is not None and self.custom_max is not None


# Spec option tables: key -> (conservative, balanced, aggressive). "rec" is the spec's
# recommended option (UD-xx "Recommendation").
_RISK: dict[str, dict[str, Any]] = {
    "breaker_pct": {
        "ref": "UD-01",
        "prompt": "Drawdown breaker: at what % drop from peak equity should new trades stop?",
        "why": "Stops opening trades after a large peak-to-trough loss; reset needs your command.",
        "opts": {"A": (8, 12, 20), "B": (10, 15, 25), "C": (12, 20, 30)},
        "rec": "B",
        "tight": "halts sooner, smaller worst-case loss; may trip in normal crypto swings",
        "loose": "more room for normal volatility; larger loss before it halts",
    },
    "daily_loss_pct": {
        "ref": "UD-02",
        "prompt": "Daily loss limit: what % loss in one UTC day locks trading until midnight?",
        "why": "Limits damage from one bad day or a malfunction. Must sit below the breaker.",
        "opts": {"A": (2, 3, 5), "B": (1.5, 3, 5), "C": (3, 5, 8)},
        "rec": "A",
        "tight": "a bad day costs less; lockouts happen more often",
        "loose": "fewer lockouts; a bad day can cost more",
    },
    "risk_per_trade_pct": {
        "ref": "UD-03",
        "prompt": "Risk per trade: what % of equity may one trade lose if its stop is hit?",
        "why": "The main sizing driver. The risk engine sizes every order from this.",
        "opts": {"A": (0.5, 1.0, 1.5), "B": (0.25, 0.5, 1.0), "C": (0.75, 1.25, 2.0)},
        "rec": "A",
        "tight": "smaller positions and losses per trade; smaller gains too",
        "loose": "bigger positions and gains; a losing streak hurts faster",
    },
    "exposure_pct": {
        "ref": "UD-12",
        "prompt": "Total exposure cap: at most what % of equity may be in coins at once?",
        "why": "Bounds total market exposure. Exposure + reserve floor must not exceed 100%.",
        "opts": {"A": (50, 80, 90), "B": (40, 70, 85), "C": (60, 80, 95)},
        "rec": "A",
        "tight": "more cash held back in a crash",
        "loose": "more of the account working in a rally",
    },
    "max_positions": {
        "ref": "UD-12",
        "prompt": "Maximum open positions at once?",
        "why": "Bounds complexity and how many coins can be held together.",
        "opts": {"A": (3, 5, 8), "B": (2, 4, 6)},
        "rec": "A",
        "tight": "simpler, more concentrated",
        "loose": "more diversified across coins",
        "integer": True,
    },
    "stop_atr_multiple": {
        "ref": "UD-16",
        "prompt": "Hard stop distance: how many ATR(14) below entry should the stop sit?",
        "why": "Placed at Kraken after every buy; with risk per trade it sets position size.",
        "opts": {"tight": (1.5, 1.5, 1.5), "standard": (2.0, 2.0, 2.0), "wide": (3.0, 3.0, 3.0)},
        "rec": "standard",
        "tight": "stopped out more often by noise; larger position for the same risk",
        "loose": "survives noise; smaller position for the same risk",
    },
}
_RESERVE: dict[str, Any] = {
    "ref": "UD-04",
    "opts": {
        "A": ((30, 60), (20, 40), (10, 25)),
        "B": ((40, 70), (25, 50), (15, 30)),
        "C": ((20, 50), (10, 30), (5, 20)),
    },
    "rec": "A",
}
_CAPS = {  # UD-13 option A (scaled H-01..H-04): Core, Major, Speculative, Speculative total
    "core_cap_pct": ("Core coins (BTC, ETH): max % of equity per coin?", (25, 35, 45)),
    "major_cap_pct": ("Major coins (SOL, XRP): max % per coin?", (10, 15, 20)),
    "spec_cap_pct": ("Speculative coins (SUI): max % per coin?", (2.5, 5, 7.5)),
    "spec_total_pct": ("All Speculative coins together: max % of equity?", (5, 10, 15)),
}
_COOLDOWN = {"A": ((2, 48), (3, 24), (4, 12)), "B": ((3, 24), (3, 24), (3, 24))}
_OPS: dict[str, tuple[str, str, tuple[Any, ...], Any]] = {
    "max_exchange_errors": (
        "Consecutive Kraken errors before the kill switch engages?",
        "UD-17",
        (3, 5),
        3,
    ),
    "stale_grace_seconds": (
        "Seconds to wait for a new candle before data counts as stale?",
        "UD-17",
        (60, 120, 300),
        120,
    ),
    "stale_cycles": (
        "Stale cycles in a row before the kill switch engages?",
        "UD-17",
        (2, 3, 5),
        3,
    ),
    "clock_skew_seconds": (
        "Allowed clock difference from Kraken (seconds)?",
        "UD-17",
        (2, 5, 10),
        5,
    ),
}


def _envelope(table: dict[str, tuple[Any, ...]]) -> tuple[float, float]:
    """Min and max over every option and preset."""
    vals = [float(v) for row in table.values() for v in row]
    return min(vals), max(vals)


def _risk_question(qid: str, spec: dict[str, Any], col: int) -> Question:
    """Build one numeric risk question for a preset column."""
    values = {k: v[col] for k, v in spec["opts"].items()}
    lo_v, hi_v = min(values.values()), max(values.values())
    opts = []
    seen: set[Any] = set()
    for key, v in sorted(values.items(), key=lambda kv: kv[1]):
        if v in seen:
            continue
        seen.add(v)
        pros = spec["tight"] if v == lo_v else spec["loose"] if v == hi_v else "middle ground"
        opts.append(
            Option(
                key,
                f"{v}" + ("" if qid in ("max_positions", "stop_atr_multiple") else "%"),
                v,
                pros=pros,
                recommended=key == spec["rec"],
            )
        )
    lo, hi = _envelope(spec["opts"])
    return Question(
        qid,
        "risk",
        spec["prompt"],
        spec["why"],
        "number",
        spec["ref"],
        tuple(opts),
        lo,
        hi,
        integer=bool(spec.get("integer")),
    )


def questions_for(
    preset: str, strategies: list[dict[str, Any]], coins: list[str]
) -> list[Question]:
    """
    The full interview for one starting preset.

    Args:
        preset (str): ``conservative``, ``balanced``, or ``aggressive``; selects which column
            of each spec option table is offered.
        strategies (list[dict[str, Any]]): ``{"id", "timeframes"}`` for strategies a session
            may run (research-only controls excluded by the caller).
        coins (list[str]): Asset IDs in the registry.

    Returns:
        list[Question]: Questions in interview order.

    Raises:
        ValueError: For an unknown preset.
    """
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    col = PRESETS.index(preset)
    qs: list[Question] = [
        Question(
            "decision_timeframe",
            "style",
            "Trading style: which chart does this profile decide on?",
            "Swing trades decide every 4 hours; quick trades every hour (more trades, more fees).",
            "choice",
            "D-16",
            (
                Option("4h", "4-hour swing", "4h", "fewer trades, lower fees", "slower", True),
                Option("1h", "1-hour quick plays", "1h", "more chances", "fees eat small moves"),
            ),
        ),
        Question(
            "strategy_id",
            "style",
            "Which strategy should this profile run?",
            "Strategies only signal a direction; the risk engine sizes every order.",
            "choice",
            "BL-022",
            tuple(Option(s["id"], s["id"], s["id"], meta_note(s), "") for s in strategies),
        ),
        Question(
            "coins",
            "universe",
            "Which coins may this profile trade?",
            "Each coin must still pass Kraken eligibility (volume, history) every cycle.",
            "multi",
            "D-24",
            tuple(Option(c, c, c) for c in coins),
        ),
        Question(
            "paper_capital_usd",
            "capital",
            "Paper (simulated) starting capital in USD?",
            "Backtests and paper trading start with this. Live money is capped separately.",
            "number",
            "D-04",
            (Option("2500", "$2,500", 2500, recommended=True), Option("250", "$250", 250)),
            100,
            1_000_000,
        ),
    ]
    qs += [_risk_question(k, v, col) for k, v in _RISK.items()]
    res_vals = {k: v[col] for k, v in _RESERVE["opts"].items()}
    res_all = [x for row in _RESERVE["opts"].values() for pair in row for x in pair]
    qs.append(
        Question(
            "reserve_pct_range",
            "risk",
            "Cash reserve: floor and defensive ceiling (% of equity kept in cash)?",
            "Cash for fees and defence. The floor + exposure cap must not exceed 100%.",
            "range",
            _RESERVE["ref"],
            tuple(
                Option(k, f"{lo}-{hi}%", [lo, hi], recommended=k == _RESERVE["rec"])
                for k, (lo, hi) in res_vals.items()
            ),
            min(res_all),
            max(res_all),
        )
    )
    for qid, (prompt, row) in _CAPS.items():
        all_v = {"x": row}
        lo, hi = _envelope(all_v)
        qs.append(
            Question(
                qid,
                "risk",
                prompt,
                "Concentration cap by tier (UD-13 option A scales the Balanced hypotheses).",
                "number",
                "UD-13",
                (Option("A", f"{row[col]}%", row[col], recommended=True),),
                lo,
                hi,
            )
        )
    qs.append(
        Question(
            "cooldown",
            "risk",
            "Cooldown: after how many losses in a row, pause that coin for how many hours?",
            "Stops a strategy from repeatedly losing on the same coin.",
            "choice",
            "UD-17",
            tuple(
                Option(k, f"{v[col][0]} losses, {v[col][1]} h", list(v[col]), recommended=k == "A")
                for k, v in _COOLDOWN.items()
                # Reason: option B equals option A for Balanced; show each distinct choice once.
                if k == "A" or v[col] != _COOLDOWN["A"][col]
            ),
        )
    )
    qs.append(
        Question(
            "intraday_cap_pct",
            "intraday",
            "Quick-trade slice: what % of the money may 1h intraday strategies use? (0 = off)",
            "An isolated slice with its own ledger and limits (D-19). Disabled until it is built.",
            "choice",
            "UD-14",
            tuple(
                Option(str(v), "off" if v == 0 else f"{v}%", v, recommended=v == 0)
                for v in (0, 5, 10, 15, 20)
            ),
        )
    )
    qs.append(
        Question(
            "intraday_limits",
            "intraday",
            "Quick-trade slice loss limits (on the slice's own money)?",
            "Keeps intraday losses from consuming the main portfolio. Ignored if the slice is off.",
            "choice",
            "UD-14",
            (
                Option("B", "half of the profile limits", "B", "stops sooner", "", True),
                Option("A", "same as the profile limits", "A", "more room", "loses more first"),
            ),
        )
    )
    for qid, (prompt, ref, vals, rec) in _OPS.items():
        qs.append(
            Question(
                qid,
                "safety",
                prompt,
                "Fail-closed safety tuning. Only the spec's options are allowed.",
                "choice",
                ref,
                tuple(Option(str(v), str(v), v, recommended=v == rec) for v in vals),
            )
        )
    qs.append(
        Question(
            "acknowledgement",
            "sign-off",
            "In your own words: you choose this profile and accept that real money can be lost.",
            "Recorded with your name and the time. Required for every owner-built profile.",
            "text",
            "D-06",
            min_length=20,
        )
    )
    return qs


def meta_note(strategy: dict[str, Any]) -> str:
    """Short note shown next to a strategy option."""
    return "timeframes: " + ", ".join(strategy.get("timeframes", []))


HEADER_QUESTIONS = (
    Question(
        "owner",
        "owner",
        "Your full name (recorded as the approver of every value)?",
        "",
        "text",
        min_length=2,
    ),
    Question(
        "profile_id",
        "owner",
        "Name for this profile (lowercase, digits, hyphens; e.g. swing-aggressive)?",
        "Becomes configs/profiles/<name>.yaml and configs/risk/<name>.yaml.",
        "text",
        pattern=r"^[a-z][a-z0-9-]{2,63}$",
    ),
    Question(
        "preset",
        "owner",
        "Starting point: which spec preset's options should be offered?",
        "Each later question offers that preset's options; you can still type a custom value.",
        "choice",
        "D-08",
        tuple(Option(p, p.title(), p, recommended=p == "balanced") for p in PRESETS),
    ),
)


def bank_json(strategies: list[dict[str, Any]], coins: list[str]) -> dict[str, Any]:
    """
    Everything the web form needs: header questions and the interview for each preset.

    Args:
        strategies (list[dict[str, Any]]): Session-runnable strategies.
        coins (list[str]): Asset IDs.

    Returns:
        dict[str, Any]: JSON-ready bank.
    """

    def dump(q: Question) -> dict[str, Any]:
        d = asdict(q)
        d["allows_custom"] = q.allows_custom
        return d

    return {
        "bank_version": 1,
        "header": [dump(q) for q in HEADER_QUESTIONS],
        "presets": {p: [dump(q) for q in questions_for(p, strategies, coins)] for p in PRESETS},
    }
