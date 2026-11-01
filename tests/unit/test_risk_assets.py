"""T-22: unsupported assets are rejected (D-47 unsupported assets; D-25)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.factories import decision, fixture_bundle, flat_candles, make_ctx
from tests.helpers import T0, series
from trader.domain.enums import ReasonCode, RiskStatus
from trader.domain.universe import AssetRegistry
from trader.risk.engine import RiskEngine
from trader.universe.eligibility import UNRESOLVED, EligibilityEvaluator
from trader.universe.registry import Registry


def _registry(**changes: object) -> Registry:
    data = fixture_bundle().registry
    assert data is not None
    raw = data.model_dump()
    if "blocked" in changes:
        for a in raw["assets"]:
            if a["asset_id"] == changes["blocked"]:
                a["blocked"] = True
    for extra in changes.get("instruments", []):  # type: ignore[attr-defined]
        raw["instruments"].append(extra)
    for extra in changes.get("assets", []):  # type: ignore[attr-defined]
        raw["assets"].append(extra)
    return Registry(AssetRegistry.model_validate(raw))


def _eval(**kw: object):  # type: ignore[no-untyped-def]
    ctx = make_ctx(**kw)  # type: ignore[arg-type]
    return RiskEngine().evaluate(decision(ctx.snapshot.instrument_id, ctx.decision_time), ctx)


def _sol() -> dict[str, object]:
    return {
        "instruments": [
            {
                "instrument_id": "SOL-USD",
                "base": "SOL",
                "quote": "USD",
                "type": "spot",
                "quantity_step": "0.0001",
            }
        ],
        "assets": [
            {
                "asset_id": "SOL",
                "name": "Solana",
                "tier": "major",
                "tier_status": "approved",
                "aliases": [],
                "blocked": False,
            }
        ],
    }


@pytest.mark.parametrize(
    ("label", "kw", "code"),
    [
        ("not_in_registry", {"inst": "DOGE-USD"}, ReasonCode.ASSET_NOT_SUPPORTED),
        ("blocked", {"registry": "blocked"}, ReasonCode.ASSET_BLOCKED),
        ("outside_profile", {"inst": "SOL-USD", "registry": "sol"}, ReasonCode.ASSET_NOT_SUPPORTED),
        ("non_spot", {"registry": "perp"}, ReasonCode.ASSET_NOT_SUPPORTED),
        ("ineligible", {"universe": "ineligible"}, ReasonCode.ASSET_INELIGIBLE),
    ],
)
def test_t22_unsupported_assets(label: str, kw: dict[str, object], code: ReasonCode) -> None:
    """T-22: each unsupported category rejects with its code; no quantity approved."""
    kw = dict(kw)
    if kw.get("registry") == "blocked":
        kw["registry"] = _registry(blocked="BTC")
    elif kw.get("registry") == "sol":
        kw["registry"] = _registry(**_sol())
    elif kw.get("registry") == "perp":
        data = fixture_bundle().registry
        assert data is not None
        raw = data.model_dump()
        raw["instruments"][0]["type"] = "perpetual"
        kw["registry"] = Registry(AssetRegistry.model_validate(raw))
    if kw.get("universe") == "ineligible":
        from tests.factories import eligible_universe

        c = flat_candles()
        kw["universe"] = eligible_universe(c[-1].close_time_utc, ["BTC-USD"], eligible=False)
    rd = _eval(**kw)
    assert rd.status == RiskStatus.REJECTED and rd.reason_codes == [code]
    assert rd.approved_quantity == 0


def test_t22_disallowed_asset() -> None:
    """T-22: an asset on the profile's disallowed list is blocked."""
    b = fixture_bundle()
    assert b.profile is not None
    uni = b.profile.universe.model_copy(update={"disallowed_assets": ["BTC"]})
    rd = _eval(profile_update={"universe": uni})
    assert rd.reason_codes == [ReasonCode.ASSET_BLOCKED]


def test_t22_btc_before_30_days_history() -> None:
    """T-22: BTC with under 30 days of history (fixture threshold) is ineligible."""
    b = fixture_bundle()
    assert b.profile is not None
    reg = Registry(b.registry)  # type: ignore[arg-type]
    short = flat_candles(n=6 * 10)  # 10 days
    long = flat_candles(n=6 * 40)  # 40 days
    for candles, expected in ((short, False), (long, True)):
        ev = EligibilityEvaluator(
            b.compiled, b.profile, reg, {"BTC-USD": candles}, {"BTC-USD": "sim"}, timedelta(hours=4)
        )
        res = ev.evaluate_one("BTC-USD", candles[-1].close_time_utc)
        assert res.eligible is expected, res.criteria
    ctx_uni = EligibilityEvaluator(
        b.compiled, b.profile, reg, {"BTC-USD": short}, {"BTC-USD": "sim"}, timedelta(hours=4)
    ).evaluate(short[-1].close_time_utc, "uni")
    rd = _eval(candles=short, universe=ctx_uni)
    assert rd.reason_codes == [ReasonCode.ASSET_INELIGIBLE]


def test_eligibility_gap_breaks_continuity() -> None:
    """Edge: a gap restarts the continuous-history count."""
    b = fixture_bundle()
    assert b.profile is not None
    c = flat_candles(n=6 * 40)
    gapped = c[: 6 * 5] + c[6 * 5 + 1 :]
    ev = EligibilityEvaluator(
        b.compiled,
        b.profile,
        Registry(b.registry),  # type: ignore[arg-type]
        {"BTC-USD": gapped},
        {"BTC-USD": "sim"},
        timedelta(hours=4),
    )
    days = [
        x
        for x in ev.evaluate_one("BTC-USD", c[-1].close_time_utc).criteria
        if x.criterion == "data_history"
    ][0]
    assert Decimal(days.observed or 0) < 36


def test_eligibility_unresolved_thresholds_fail_closed() -> None:
    """Failure: with the shipped TBD thresholds every asset is ineligible."""
    from tests.conftest import PROFILE
    from trader.domain.enums import Environment
    from trader.profiles.compiler import compile_bundle

    b = compile_bundle(PROFILE, Environment.BACKTEST)
    assert b.profile is not None
    c = series([100] * 300, start=T0)
    ev = EligibilityEvaluator(
        b.compiled,
        b.profile,
        Registry(b.registry),  # type: ignore[arg-type]
        {"BTC-USD": c},
        {"BTC-USD": "sim"},
        timedelta(hours=4),
    )
    res = ev.evaluate_one("BTC-USD", c[-1].close_time_utc)
    assert not res.eligible and res.reason == UNRESOLVED


def test_eligibility_unknown_venue_unsupported() -> None:
    """Failure: no market mapping for the dataset venue."""
    b = fixture_bundle()
    assert b.profile is not None
    c = flat_candles(n=6 * 40)
    ev = EligibilityEvaluator(
        b.compiled,
        b.profile,
        Registry(b.registry),  # type: ignore[arg-type]
        {"BTC-USD": c},
        {"BTC-USD": "kraken"},
        timedelta(hours=4),
    )
    assert not ev.evaluate_one("BTC-USD", c[-1].close_time_utc).eligible
    assert ev.evaluate_one("DOGE-USD", c[-1].close_time_utc).reason == "ASSET_NOT_SUPPORTED"
