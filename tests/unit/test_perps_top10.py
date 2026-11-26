"""The ten-coin hourly paper account, exact borrow accrual and paced candle requests (ADR-051).

Values are TEST FIXTURES with no market meaning, except the shipped configs read on purpose.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

import trader.cli.perps as perps_cli
from tests.conftest import ROOT, SHIPPED_CONFIGS, dump, load
from tests.perps_support import T0, fixture_file, fixture_params
from trader.cli.main import app
from trader.ops.health import EXPECTED_SERVICES
from trader.perps.candles import PacedFetcher
from trader.perps.math import PerpSide
from trader.perps.params import (
    PerpsConfigFile,
    PerpsConfigUnresolvedError,
    load_perps_file,
    load_perps_params,
)
from trader.perps.review_agents import load_assistant_settings
from trader.perps.review_facts import ACCOUNTS as REVIEW_ACCOUNTS
from trader.perps.session import PerpsSession
from trader.perps.signals import DEFAULT_SIGNAL, make_signal
from trader.perps.simulator import CENT, PaperPerpsAccount
from trader.ui.data import kraken_has, kraken_public_ohlc

COINS = ["BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "HYPE", "ZEC", "DOGE", "LINK"]
RISING = {"BTC", "ETH", "BNB", "XRP", "SOL"}
STEP = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
NOW = datetime(2026, 11, 16, 6, 4, tzinfo=UTC)
ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


def _price(symbol: str, t: datetime) -> float:
    """A steady climb for half the coins and a steady fall for the rest."""
    rate = 0.0005 if symbol.split("/")[0] in RISING else -0.0005
    return 100 * math.exp(rate * ((t - ORIGIN) / timedelta(hours=1)))


def _feed_at(now: datetime) -> Any:
    """A fetcher returning 720 rows like Kraken's (the last one forming) as of ``now``."""

    def feed(symbol: str, tf: str) -> list[list[float]]:
        step = STEP[tf]
        last = now.replace(minute=0, second=0, microsecond=0)
        if tf == "4h":
            last = last.replace(hour=last.hour // 4 * 4)
        rows = []
        for i in range(720):
            o = last - step * (719 - i)
            po, pc = _price(symbol, o), _price(symbol, min(o + step, now))
            rows.append(
                [int(o.timestamp() * 1000), po, max(po, pc) * 1.001, min(po, pc) * 0.999, pc, 1.0]
            )
        return rows

    return feed


def _session(tmp: Path, now: datetime, **kw: Any) -> PerpsSession:
    return PerpsSession(
        load_perps_params(SHIPPED_CONFIGS, "top10.yaml"),
        _feed_at(now),
        tmp / "state.json",
        tmp / "events.jsonl",
        signal=make_signal(DEFAULT_SIGNAL, 6),
        signal_name=DEFAULT_SIGNAL,
        timeframe="1h",
        trend_timeframe="4h",
        **kw,
    )


# --- the settings file -----------------------------------------------------------------------
def test_top10_file_holds_the_owner_values_and_is_listed_everywhere() -> None:
    p = load_perps_params(SHIPPED_CONFIGS, "top10.yaml")
    assert list(p.markets) == COINS  # decisions are taken in the file's order
    assert all(kraken_has(f"{m}/USD") for m in p.markets)
    assert p.starting_collateral_usd == D(2500)
    assert p.max_collateral_per_position_pct == D(1)
    assert p.liquidation_buffer_daily_moves == D(8)
    assert p.max_leverage == p.target_leverage == D(5)
    assert p.stop_loss_pct_of_collateral == D(30)  # owner rule: every trade has a stop
    assert p.take_profits == ((D(4), D(25)), (D(8), D(25)), (D(12), D(50)))
    assert p.max_open_positions == 10 and p.daily_loss_limit_pct == D(15)
    assert (p.open_fee_bps, p.close_fee_bps) == (D(7), D(7))
    assert p.borrow_rate_pct_per_hour == D("0.0016")
    cfg = load_perps_file(SHIPPED_CONFIGS, "top10.yaml")
    assert cfg.venue == "generic_perps" and cfg.mode == "paper" and cfg.price_mints() == {}
    assert (
        perps_cli.ACCOUNTS["top10"][:2] == REVIEW_ACCOUNTS["top10"] == ("top10.yaml", "perps-top10")
    )
    assert perps_cli.FIXED_TIMEFRAMES["top10"] == "1h" and "top10" in perps_cli.PACING
    assert "perps-top10" in EXPECTED_SERVICES
    command = load(ROOT / "docker-compose.yml")["services"]["perps-top10"]["command"]
    assert command == ["perps", "paper", "run", "--account", "top10", "--timeframe", "1h"]
    services = next(
        line
        for line in (ROOT / "scripts/ops/common.sh").read_text().splitlines()
        if line.startswith("PAPER_SERVICES=")
    )
    assert " perps-top10 " in services and "live" not in services
    assistant = load_assistant_settings(SHIPPED_CONFIGS)
    assert "top10" in assistant.accounts and "top10" in assistant.report_accounts


def test_jupiter_files_are_unchanged_by_the_generic_venue() -> None:
    for name in ("jupiter.yaml", "jupiter-degen.yaml", "jupiter-spot-perps.yaml"):
        cfg = load_perps_file(SHIPPED_CONFIGS, name)
        assert cfg.venue == "jupiter_perps" and set(cfg.price_mints()) == {"SOL", "ETH", "BTC"}
        assert all(len(mint) >= 32 for mint in cfg.price_mints().values())


@pytest.mark.parametrize(
    ("venue", "markets", "why"),
    [
        ("generic_perps", [{"market": "DOGE", "price_mint": "x" * 40}], "takes no price_mint"),
        ("jupiter_perps", [{"market": "DOGE", "price_mint": "x" * 40}], "lists only"),
        ("jupiter_perps", [{"market": "SOL"}], "needs a price_mint"),
        ("generic_perps", [{"market": "DOGE"}, {"market": "DOGE"}], "must not repeat"),
        ("generic_perps", [{"market": "doge"}], "String should match pattern"),
        ("generic_perps", [{"market": "../../x"}], "String should match pattern"),
    ],
)
def test_markets_must_fit_the_venue(venue: str, markets: list[dict[str, str]], why: str) -> None:
    with pytest.raises(ValidationError, match=why):
        PerpsConfigFile.model_validate({**fixture_file(), "venue": venue, "markets": markets})


def test_a_generic_venue_still_fails_closed_on_tbd(tmp_path: Path) -> None:
    data = load(SHIPPED_CONFIGS / "perps" / "top10.yaml")
    data["risk"]["max_collateral_per_position_pct"] = {
        "value": "TBD",
        "status": "unresolved",
        "ref": "UD-33",
    }
    dump(tmp_path / "perps" / "top10.yaml", data)
    with pytest.raises(PerpsConfigUnresolvedError, match="max_collateral_per_position_pct"):
        load_perps_params(tmp_path, "top10.yaml")


# --- borrow accrual ----------------------------------------------------------------------------
def _small_account() -> PaperPerpsAccount:
    """A $125 position on $25 of collateral: the size the ten-coin account trades."""
    params = fixture_params(
        max_collateral_per_position_pct="2.5",
        target_leverage="5",
        borrow_rate_pct_per_hour="0.0016",
    )
    a = PaperPerpsAccount.start(params, T0)
    assert a.open("SOL", PerpSide.LONG, {"SOL": D(100)}, T0).approved
    assert a.positions["SOL"].size_usd == D(125)
    return a


def test_borrow_accrues_exactly_on_a_small_hourly_position() -> None:
    a = _small_account()
    for hour in range(1, 25):
        a.mark({"SOL": D(100)}, T0 + timedelta(hours=hour))
    # 125 * 0.0016% = $0.002 an hour. Rounded to a cent every hour this used to be $0.00.
    assert a.positions["SOL"].borrow_fees_usd == D("0.048")
    a.close("SOL", {"SOL": D(100)}, T0 + timedelta(hours=24), "TEST")
    closed = a.events[-1]
    # Paid in whole cents at the close: $0.08 close fee (125 * 6 bps) + $0.05 borrow.
    assert closed["fees_usd"] == "0.13"
    assert a.cash_usd == D(1000) - D("0.08") - D("0.13") == a.cash_usd.quantize(CENT)
    assert a.fees_paid_usd == D("0.21")


def test_one_long_accrual_equals_many_short_ones() -> None:
    hourly, once = _small_account(), _small_account()
    for hour in range(1, 101):
        hourly.mark({"SOL": D(100)}, T0 + timedelta(hours=hour))
    once.mark({"SOL": D(100)}, T0 + timedelta(hours=100))
    assert hourly.positions["SOL"].borrow_fees_usd == once.positions["SOL"].borrow_fees_usd
    assert once.positions["SOL"].borrow_fees_usd == D("0.2")


def test_a_partial_close_never_pays_more_borrow_than_has_accrued() -> None:
    a = _small_account()
    a.positions["SOL"].borrow_fees_usd = D("0.006")
    a._close_part("SOL", D("0.9"), D(100), T0 + timedelta(hours=3), 1)
    # 0.006 * 0.9 rounds up to a cent, more than the $0.006 owed: nothing is paid yet.
    assert a.positions["SOL"].borrow_fees_usd == D("0.006")
    assert a.cash_usd == a.cash_usd.quantize(CENT)
    # A balance already in cents (state saved before ADR-051) splits as it always did.
    b = _small_account()
    b.positions["SOL"].borrow_fees_usd = D("0.13")
    b._close_part("SOL", D("0.25"), D(100), T0 + timedelta(hours=3), 1)
    assert b.positions["SOL"].borrow_fees_usd == D("0.10")


# --- the session ---------------------------------------------------------------------------------
def test_first_cycle_opens_small_stopped_positions_long_and_short(tmp_path: Path) -> None:
    s = _session(tmp_path, NOW)
    opened = {e["market"]: e for e in s.cycle(NOW) if e["event"] == "OPENED"}
    assert list(opened) == COINS
    assert {m for m, e in opened.items() if e["side"] == "long"} == RISING
    assert s.acct is not None and len(s.acct.positions) == 10
    for e in opened.values():
        assert D("24.5") < D(e["collateral_usd"]) <= D(25)  # 1% of about $2,500
        assert D(e["leverage"]) <= 5
    for p in s.acct.positions.values():
        stop = s.acct.stop_price(p)
        assert stop is not None and p.initial_stop == stop
        # 30% of the collateral at 5x or less: the stop is at least 5% from entry.
        assert abs(stop - p.entry_price) / p.entry_price > D("0.05")
    assert s.meta["timeframe"] == "1h" and s.meta["trend_timeframe"] == "4h"
    assert s.meta["markets"] == sorted(COINS)


def test_restart_keeps_sub_cent_borrow(tmp_path: Path) -> None:
    _session(tmp_path, NOW).cycle(NOW)
    later = NOW + timedelta(hours=1)
    again = _session(tmp_path, later)
    again.cycle(later)
    assert again.acct is not None
    borrow = again.acct.positions["BTC"].borrow_fees_usd
    assert D(0) < borrow < CENT  # 56 minutes on about $125: a fraction of a cent
    saved = json.loads((tmp_path / "state.json").read_text())
    assert D(saved["account"]["positions"]["BTC"]["borrow_fees_usd"]) == borrow


def test_settle_seconds_delays_the_cycle_and_must_fit_inside_a_bar(tmp_path: Path) -> None:
    s = _session(tmp_path, NOW, settle_seconds=180)
    s.cycle(NOW)  # processes the 05:00 bar; the 06:00 bar closes at 07:00
    close = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
    assert not s.due(close + timedelta(seconds=179))
    assert s.due(close + timedelta(seconds=180))
    default = _session(tmp_path, NOW)
    assert default.due(close + timedelta(seconds=90))
    with pytest.raises(ValueError, match="settle_seconds"):
        _session(tmp_path / "x", NOW, settle_seconds=3600)


# --- paced requests ------------------------------------------------------------------------------
class _Time:
    """A clock that only moves when something sleeps or the test advances it."""

    def __init__(self) -> None:
        self.t, self.slept = 0.0, []

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def test_paced_fetcher_spaces_requests() -> None:
    time = _Time()
    paced = PacedFetcher(lambda symbol, tf: [[1.0]], clock=time.clock, sleep=time.sleep)
    assert paced("BTC/USD", "1h") == [[1.0]] and time.slept == []  # the first call never waits
    paced("ETH/USD", "1h")
    assert time.slept == [1.0]
    time.t += 0.4
    paced("SOL/USD", "1h")
    assert time.slept == [1.0, pytest.approx(0.6)]
    time.t += 5
    paced("XRP/USD", "1h")
    assert len(time.slept) == 2  # long enough ago: no wait


def test_paced_fetcher_retries_a_refused_request_then_gives_up() -> None:
    time, calls = _Time(), []

    def flaky(symbol: str, tf: str) -> list[list[float]]:
        calls.append(symbol)
        if len(calls) < 3:
            raise ValueError("kraken: ['EAPI:Rate limit exceeded']")
        return [[2.0]]

    paced = PacedFetcher(flaky, clock=time.clock, sleep=time.sleep)
    assert paced("BTC/USD", "4h") == [[2.0]]
    assert calls == ["BTC/USD"] * 3 and time.slept == [3.0, 8.0]

    def down(symbol: str, tf: str) -> list[list[float]]:
        calls.append("down")
        raise OSError("network is unreachable")

    with pytest.raises(OSError, match="unreachable"):
        PacedFetcher(down, clock=time.clock, sleep=time.sleep)("BTC/USD", "4h")
    assert calls.count("down") == 3  # one try and two retries, never an endless loop
    with pytest.raises(ValueError, match="negative"):
        PacedFetcher(down, spacing_s=-1)


def test_an_unknown_symbol_is_refused_before_any_request() -> None:
    assert kraken_has("DOGE/USD") and not kraken_has("ABC/USD")
    with pytest.raises(ValueError, match="no Kraken pair"):
        kraken_public_ohlc("ABC/USD", "1h")


# --- the command line ----------------------------------------------------------------------------
@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Shipped configs, a temp data folder, a fake feed, and no real waiting."""
    import trader.ui.data as ui_data

    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", _feed_at(datetime.now(UTC)))
    monkeypatch.setattr(perps_cli, "PACING", {"top10": (0.0, 180)})
    return tmp_path


def test_cli_runs_the_top10_account_hourly(cli: Path) -> None:
    r = CliRunner().invoke(app, ["perps", "validate", "--account", "top10"])
    assert r.exit_code == 0 and "1% collateral per position, buffer 8 daily moves" in r.output
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once", "--account", "top10"])
    assert r.exit_code == 0, r.output
    state = json.loads((cli / "state" / "perps-top10.json").read_text())
    assert state["meta"]["timeframe"] == "1h" and state["meta"]["trend_timeframe"] == "4h"
    assert len(state["account"]["positions"]) == 10
    assert not (cli / "state" / "perps-paper.json").exists()  # no other account is touched
    r = CliRunner().invoke(app, ["perps", "paper", "status", "--account", "top10"])
    assert f"({DEFAULT_SIGNAL}, 1h)" in r.output and "long BTC" in r.output


def test_cli_refuses_another_timeframe_and_a_coin_without_a_feed(
    cli: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = ["perps", "paper", "run", "--once", "--account", "top10"]
    r = CliRunner().invoke(app, [*run, "--timeframe", "4h"])
    assert r.exit_code == 2 and "only runs on 1h" in r.output
    assert not (cli / "state" / "perps-top10.json").exists()
    assert perps_cli.resolve_timeframe("main", None) == "4h"
    assert perps_cli.resolve_timeframe("degen", "1h") == "1h"
    data = load(SHIPPED_CONFIGS / "perps" / "top10.yaml")
    data["markets"][-1] = {"market": "ABC"}
    dump(cli / "configs" / "perps" / "top10.yaml", data)
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(cli / "configs"))
    r = CliRunner().invoke(app, run)
    assert r.exit_code == 2 and "no public candle feed is listed for ABC" in r.output
    assert not (cli / "state" / "perps-top10.json").exists()
