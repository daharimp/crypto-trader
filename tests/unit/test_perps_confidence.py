"""Size inside the owner's range, chosen by a confidence score (ADR-054): off unless set.

Values below are TEST FIXTURES with no market meaning, except where the shipped config files
are read on purpose.
"""

from __future__ import annotations

import json
import math
import random
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from typer.testing import CliRunner

import trader.cli.perps as perps_cli
from tests.conftest import SHIPPED_CONFIGS, dump, load
from tests.perps_support import T0, fixture_file, fixture_params
from trader.cli.main import app
from trader.perps.backtest import Bar
from trader.perps.confidence import (
    CLOSES_USED,
    LOOKBACK,
    breadth,
    confidence,
    confidence_at,
    timeframe_agreement,
    trend_strength,
)
from trader.perps.math import PerpSide
from trader.perps.params import (
    MIN_SIZE_KEY,
    PerpsConfigFile,
    PerpsConfigUnresolvedError,
    load_perps_params,
    resolve,
    settings_summary,
)
from trader.perps.risk import AccountView, check_open, collateral_pct, size_open
from trader.perps.session import PerpsSession
from trader.perps.simulator import PaperPerpsAccount
from trader.regimes.trend import efficiency_ratio

LONG, SHORT = PerpSide.LONG, PerpSide.SHORT
M = {"SOL": D(100), "ETH": D(2000)}
SHIPPED = ("jupiter.yaml", "jupiter-degen.yaml", "jupiter-spot-perps.yaml", "top10.yaml")
RANGE = {MIN_SIZE_KEY: "10"}  # with the fixture's 20% cap: 10% to 20% of equity
CHOP = [D(100 + i % 2) for i in range(800)]  # up one, down one, for ever
CLIMB = [D(100 + i) for i in range(800)]  # a straight line


# --- the three readings ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("others", "expected"),
    [
        ([LONG, LONG, LONG], "1"),
        ([SHORT, None, SHORT], "0"),  # a flat market does not agree
        ([LONG, SHORT, None, LONG], "0.5"),
        ([], "0.5"),  # an account with one market has no breadth to read
    ],
)
def test_breadth_is_the_share_of_other_markets_on_the_same_side(
    others: list[PerpSide | None], expected: str
) -> None:
    assert breadth(LONG, others) == D(expected)


def test_trend_strength_ranks_the_latest_efficiency_ratio_among_its_past() -> None:
    assert trend_strength(CHOP + CLIMB[:181]) > D("0.99")  # straighter than it has been
    assert trend_strength(CLIMB + CHOP[:181]) < D("0.01")  # choppier than it has been


def test_trend_strength_matches_a_plain_reference_on_random_prices() -> None:
    rng = random.Random(7)
    closes = [D(1000)]
    for _ in range(900):
        closes.append(closes[-1] + D(rng.randint(-50, 55)) / 10)
    ratios = [efficiency_ratio(closes[max(0, i - 180) : i + 1]) for i in range(len(closes))]
    earlier = [r for r in ratios[-1 - LOOKBACK : -1] if r is not None]
    now = ratios[-1]
    assert now is not None and len(earlier) == LOOKBACK
    below, equal = sum(r < now for r in earlier), sum(r == now for r in earlier)
    assert trend_strength(closes) == (D(below) + D(equal) / 2) / LOOKBACK
    # Reason: nothing older than the last 721 closes may matter (the exchange keeps 720).
    assert trend_strength([D(1)] * 500 + closes[-CLOSES_USED:]) == trend_strength(closes)


@pytest.mark.parametrize(
    "closes",
    [[], CLIMB[:181], CLIMB[:300], [D(100)] * 800],
    ids=["no candles", "one reading", "too little history", "no movement"],
)
def test_trend_strength_without_enough_to_compare_is_neutral(closes: list[D]) -> None:
    assert trend_strength(closes) == D("0.5")


def test_timeframe_agreement_counts_the_two_longer_views() -> None:
    up, down = CLIMB[:250], CLIMB[:250][::-1]
    assert timeframe_agreement(LONG, up, up) == 1
    assert timeframe_agreement(SHORT, up, up) == 0
    assert timeframe_agreement(SHORT, down, down) == 1
    assert timeframe_agreement(LONG, up, down) == D("0.5")
    # A view without 200 closes, or exactly level, is neither for nor against.
    assert timeframe_agreement(LONG, up, up[:199]) == D("0.75")
    assert timeframe_agreement(LONG, up[:199], down) == D("0.25")
    assert timeframe_agreement(LONG, [], []) == D("0.5")
    assert timeframe_agreement(LONG, [D(100)] * 250, [D(100)] * 250) == D("0.5")


def test_confidence_is_the_plain_average_and_stays_between_0_and_1() -> None:
    best = confidence(LONG, [LONG, LONG], CHOP + CLIMB[:400], CLIMB[:250])
    worst = confidence(SHORT, [LONG, LONG], CHOP + CLIMB[:400], CLIMB[:250])
    assert D("0.9") < best <= 1 and 0 <= worst < D("0.4")
    assert confidence(LONG, [], [], []) == D("0.5")  # nothing known: the middle of the range


def test_confidence_at_reads_only_candles_closed_at_the_decision() -> None:
    def bars(closes: list[D], step: timedelta) -> list[Bar]:
        return [Bar(T0 + i * step, c, c, c, c) for i, c in enumerate(closes)]

    four, day = timedelta(hours=4), timedelta(days=1)
    decided = T0 + 4 * 300 * four  # the 1,200th 4h candle and the 200th day have just closed
    c4, c1 = bars(CLIMB + CLIMB[:500], four), bars(CLIMB[:201], day)
    base = confidence_at(decided, LONG, [LONG], c4, c1)
    assert base == confidence(LONG, [LONG], [b.close for b in c4[:1200]], CLIMB[:200])
    # Changing the candles still forming at the decision changes nothing ...
    later4 = [*c4[:1200], Bar(c4[1200].open_time_utc, *[D(1)] * 4)]
    later1 = [*c1[:200], Bar(c1[200].open_time_utc, *[D(1)] * 4)]
    assert confidence_at(decided, LONG, [LONG], later4, later1) == base
    # ... and changing one that had closed does (the control).
    moved = [*c1[:199], Bar(c1[199].open_time_utc, *[D(1)] * 4), c1[200]]
    assert confidence_at(decided, LONG, [LONG], c4, moved) != base


# --- the size rule ---------------------------------------------------------------------------
def test_without_a_range_every_position_posts_the_cap() -> None:
    p = fixture_params()
    assert p.min_collateral_per_position_pct is None
    assert collateral_pct(p, None) == collateral_pct(p, D("0.1")) == D(20)


@pytest.mark.parametrize(
    ("score", "pct"),
    [("0", "10"), ("0.5", "15"), ("1", "20"), ("0.3333", "13.333"), ("-3", "10"), ("7", "20")],
)
def test_a_range_maps_the_score_to_a_size_and_never_leaves_it(score: str, pct: str) -> None:
    assert collateral_pct(fixture_params(**RANGE), D(score)) == D(pct)


def test_rounding_never_carries_a_size_past_an_end_of_the_range() -> None:
    odd = {MIN_SIZE_KEY: "10.00004", "max_collateral_per_position_pct": "19.99996"}
    p = fixture_params(**odd)
    assert collateral_pct(p, D(0)) == D("10.00004")  # 10.0000 would be under the smallest
    assert collateral_pct(p, D(1)) == D("19.99996")  # 20.0000 would be over the largest
    assert collateral_pct(p, D("0.5")) == D("15.0000")


def test_an_unknown_score_refuses_the_open() -> None:
    p = fixture_params(**RANGE)
    view = AccountView(D(1000), D(1000), D(1000), frozenset(), D(0), False)
    proposal = size_open(p, view, "SOL", LONG, D(100))
    assert collateral_pct(p, None) == 0 and proposal.collateral_usd == 0
    decision = check_open(p, view, proposal)
    assert not decision.approved and decision.reasons == ["PERP_CONFIDENCE_UNAVAILABLE"]


def test_the_account_sizes_each_open_by_the_score_it_is_handed() -> None:
    a = PaperPerpsAccount.start(fixture_params(**RANGE), T0)
    a.confidence = {"SOL": D(1), "ETH": D("0.25")}
    assert a.open("SOL", LONG, M, T0).approved
    assert a.positions["SOL"].collateral_usd == D(200)  # 20% of 1,000
    worth = a.equity(M)  # 999.28: the opening fee paid and the closing fee owed
    assert a.open("ETH", SHORT, M, T0).approved
    assert a.positions["ETH"].collateral_usd == D("124.91") == (worth / 8).quantize(D("0.01"))
    assert [(e["confidence"], e["collateral_pct"]) for e in a.events[1:]] == [
        ("1.0000", "20.0000"),
        ("0.2500", "12.5000"),
    ]
    b = PaperPerpsAccount.start(fixture_params(**RANGE), T0)
    assert not b.open("SOL", LONG, M, T0).approved  # no score handed over: refused
    assert b.events[-1]["reasons"] == ["PERP_CONFIDENCE_UNAVAILABLE"]


def test_an_account_without_a_range_ignores_a_score() -> None:
    a = PaperPerpsAccount.start(fixture_params(), T0)
    a.confidence = {"SOL": D("0.1")}
    assert a.open("SOL", LONG, M, T0).approved
    assert a.positions["SOL"].collateral_usd == D(200)
    assert "confidence" not in a.events[-1] and "collateral_pct" not in a.events[-1]


# --- the setting -----------------------------------------------------------------------------
def test_no_shipped_account_has_a_range_yet() -> None:
    for name in SHIPPED:
        p = load_perps_params(SHIPPED_CONFIGS, name)
        assert p.min_collateral_per_position_pct is None
        assert settings_summary(p)["min_collateral_pct"] is None


@pytest.mark.parametrize("low", ["0.5", "10", "20"])
def test_an_approved_range_resolves(low: str) -> None:
    p = fixture_params(**{MIN_SIZE_KEY: low})  # "20" is the cap: a fixed size, score recorded
    assert p.min_collateral_per_position_pct == D(low)
    assert settings_summary(p)["min_collateral_pct"] == low


@pytest.mark.parametrize(("bad", "why"), [("0", "positive"), ("-5", "positive"), ("21", "exceed")])
def test_a_bad_bottom_of_the_range_is_refused(bad: str, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        fixture_params(**{MIN_SIZE_KEY: bad})


def test_a_tbd_bottom_of_the_range_fails_closed() -> None:
    f = fixture_file()
    f["risk"][MIN_SIZE_KEY] = {"value": "TBD", "status": "unresolved", "ref": "UD-35"}
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        resolve(PerpsConfigFile.model_validate(f))
    assert exc.value.keys == [f"risk.{MIN_SIZE_KEY}"]


# --- the session -----------------------------------------------------------------------------
H4 = timedelta(hours=4)


class _Feed:
    """SOL climbs and ETH falls (or climbs too); records which timeframes were asked for."""

    def __init__(self, eth_rate: float) -> None:
        self.rates = {"SOL/USD": 1.01, "ETH/USD": eth_rate}
        self.asked: list[tuple[str, str]] = []

    def __call__(self, symbol: str, timeframe: str) -> list[list[float]]:
        self.asked.append((symbol, timeframe))
        step = timedelta(days=1) if timeframe == "1d" else H4
        rows, prev = [], 100.0
        for i in range(61 if timeframe == "4h" else 12):
            c = prev * self.rates[symbol]
            rows.append([int((T0 + i * step).timestamp() * 1000), prev, c, prev, c, 1.0])
            prev = c
        return rows


def _signal(closes: list[D]) -> PerpSide | None:
    return LONG if closes[-1] > closes[-2] else SHORT


def _first_cycle(tmp: Path, feed: _Feed, **overrides: str) -> PaperPerpsAccount:
    s = PerpsSession(
        fixture_params(**overrides),
        feed,
        tmp / "state.json",
        tmp / "events.jsonl",
        signal=_signal,
        signal_name="scripted",
    )
    s.cycle(T0 + 60 * H4 + timedelta(minutes=2))
    assert s.acct is not None
    return s.acct


def test_session_scores_each_open_and_counts_the_other_markets(tmp_path: Path) -> None:
    # Both markets long: breadth 1; too little history for the other two readings (0.5 each).
    agree = _first_cycle(tmp_path / "a", _Feed(1.01), **RANGE)
    assert {m: p.side for m, p in agree.positions.items()} == {"SOL": LONG, "ETH": LONG}
    # SOL long while ETH is short: breadth 0 for both.
    split = _first_cycle(tmp_path / "b", _Feed(0.99), **RANGE)
    assert {m: p.side for m, p in split.positions.items()} == {"SOL": LONG, "ETH": SHORT}
    two_thirds, one_third = (D(1) + D("0.5") + D("0.5")) / 3, (D(0) + D("0.5") + D("0.5")) / 3
    assert agree.confidence == {"SOL": two_thirds, "ETH": two_thirds}
    assert split.confidence == {"SOL": one_third, "ETH": one_third}
    assert agree.positions["SOL"].collateral_usd == D("166.66")  # 16.6667% of 1,000
    assert split.positions["SOL"].collateral_usd == D("133.33")  # 13.3333% of 1,000


def test_session_asks_for_daily_candles_only_when_it_sizes_inside_a_range(tmp_path: Path) -> None:
    flat, ranged = _Feed(1.01), _Feed(1.01)
    plain = _first_cycle(tmp_path / "a", flat)
    _first_cycle(tmp_path / "b", ranged, **RANGE)
    assert {tf for _, tf in flat.asked} == {"4h"}
    assert {tf for _, tf in ranged.asked} == {"4h", "1d"}
    assert plain.confidence == {} and plain.positions["SOL"].collateral_usd == D(200)


class _Clocked:
    """Candles as of ``now``: ETH climbs; SOL climbs until ``turn`` then falls; one bad day."""

    def __init__(self, turn: datetime, bad_day: datetime) -> None:
        self.now, self.turn, self.bad_day = T0, turn, bad_day

    def __call__(self, symbol: str, timeframe: str) -> list[list[float]]:
        step = timedelta(days=1) if timeframe == "1d" else H4
        done = int((self.now - T0) / step)  # candles completed as of now; one more is forming
        rows = []
        for i in range(max(0, done - (300 if timeframe == "1d" else 60)), done + 1):
            closes = T0 + (i + 1) * step
            c = 100 + 0.01 * i
            if timeframe == "1d" and closes == self.bad_day:
                c = 50.0
            elif timeframe == "4h" and symbol == "SOL/USD" and closes > self.turn:
                c -= 0.02 * ((closes - self.turn) / H4)
            rows.append([int((T0 + i * step).timestamp() * 1000), c, c, c, c, 1.0])
        return rows


def test_session_catching_up_scores_a_bar_only_from_candles_closed_by_then(tmp_path: Path) -> None:
    # Midnight ends a day that closed far below its 200-day average. SOL turns down at the
    # bar closing four hours earlier, and the session only runs after midnight, so it handles
    # that bar late: its short must be scored without the day that had not closed yet.
    midnight = T0 + timedelta(days=251)
    feed = _Clocked(turn=midnight - 2 * H4, bad_day=midnight)
    s = PerpsSession(
        fixture_params(**RANGE),
        feed,
        tmp_path / "state.json",
        tmp_path / "events.jsonl",
        signal=_signal,
        signal_name="scripted",
    )
    feed.now = midnight - 2 * H4 + timedelta(minutes=2)
    first = [e for e in s.cycle(feed.now) if e["event"] == "OPENED"]
    # Both long, the daily view agrees, too little 4h history: (1 + 0.5 + 0.75) / 3.
    assert [(e["market"], e["side"], e["confidence"]) for e in first] == [
        ("SOL", "long", "0.7500"),
        ("ETH", "long", "0.7500"),
    ]
    feed.now = midnight + timedelta(minutes=2)
    late = [e for e in s.cycle(feed.now) if e["event"] == "OPENED"]
    # ETH is long (breadth 0) and the last day closed by then was above its average (the
    # daily view disagrees with a short): (0 + 0.5 + 0.25) / 3. Seeing the bad day too early
    # would have made it (0 + 0.5 + 0.75) / 3.
    assert [(e["market"], e["side"], e["confidence"]) for e in late] == [("SOL", "short", "0.2500")]
    assert s.meta["cycles"] == 3  # the first bar, then two at once


# --- the command line ------------------------------------------------------------------------
STEPS = {"1h": timedelta(hours=1), "4h": H4, "1d": timedelta(days=1)}
RISING = {"BTC", "ETH", "BNB", "XRP", "SOL"}  # five of the ten coins climb, five fall


def _kraken_like(now: datetime, asked: set[str]) -> object:
    """720 rows a timeframe like Kraken's (the last one forming): a steady climb or fall."""

    def feed(symbol: str, tf: str) -> list[list[float]]:
        asked.add(tf)
        step, rate = STEPS[tf], 0.0005 if symbol.split("/")[0] in RISING else -0.0005
        seconds = step.total_seconds()
        last = datetime.fromtimestamp(now.timestamp() // seconds * seconds, UTC)
        rows = []
        for i in range(720):
            o = last - step * (719 - i)
            po, pc = (
                100 * math.exp(rate * ((t - now) / timedelta(hours=1)))
                for t in (o, min(o + step, now))
            )
            rows.append([int(o.timestamp() * 1000), po, max(po, pc), min(po, pc), pc, 1.0])
        return rows

    return feed


def test_cli_runs_an_account_with_a_range_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import trader.ui.data as ui_data

    # A copy of the shipped settings with a TEST FIXTURE range; the shipped file has none.
    configs, asked = tmp_path / "configs", set[str]()
    shutil.copytree(SHIPPED_CONFIGS, configs)
    data = load(configs / "perps" / "top10.yaml")
    data["risk"][MIN_SIZE_KEY] = {**data["risk"]["max_collateral_per_position_pct"], "value": 0.5}
    dump(configs / "perps" / "top10.yaml", data)
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(configs))
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", _kraken_like(datetime.now(UTC), asked))
    monkeypatch.setattr(perps_cli, "PACING", {"top10": (0.0, 180)})
    r = CliRunner().invoke(app, ["perps", "validate", "--account", "top10"])
    assert r.exit_code == 0, r.output
    assert "0.5% to 1% (chosen by confidence) collateral per position, buffer" in r.output
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once", "--account", "top10"])
    assert r.exit_code == 0, r.output
    assert asked == {"1h", "4h", "1d"}
    lines = (tmp_path / "logs" / "perps-top10-events.jsonl").read_text().splitlines()
    opened = [e for e in map(json.loads, lines) if e["event"] == "OPENED"]
    assert len(opened) == 10
    # Four of the nine other coins agree (4/9), every trend is equally straight (0.5), and
    # both longer views agree (1): a score of 0.6481, so 0.5% + 0.5 x 0.6481 of the account.
    assert {(e["confidence"], e["collateral_pct"]) for e in opened} == {("0.6481", "0.8241")}
    assert all(D("20.5") < D(e["collateral_usd"]) < D("20.7") for e in opened)
