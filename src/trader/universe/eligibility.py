"""Point-in-time eligibility and ``UniverseSnapshot`` (D-25, §7.6)."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median

from trader.domain.candles import Candle
from trader.domain.compiled import CompiledProfile
from trader.domain.profiles import TradingProfile
from trader.domain.universe import AssetEligibility, CriterionOutcome, UniverseSnapshot

from .registry import Registry

UNRESOLVED = "ELIGIBILITY_THRESHOLD_UNRESOLVED"
LIQUIDITY_DAYS = 30


class _History:
    """Pre-computed daily quote volumes and continuity segments for one instrument."""

    def __init__(self, candles: list[Candle], timeframe_delta: timedelta) -> None:
        """
        Pre-compute daily sums and segment starts.

        Args:
            candles (list[Candle]): All candles (sorted).
            timeframe_delta (timedelta): Bar length.
        """
        daily: dict[date, Decimal] = defaultdict(Decimal)
        for c in candles:
            daily[c.open_time_utc.date()] += c.volume * c.close
        self.daily = dict(daily)
        self.segment_starts: list[datetime] = []
        prev: Candle | None = None
        for c in candles:
            if prev is None or c.open_time_utc - prev.open_time_utc > timeframe_delta:
                self.segment_starts.append(c.open_time_utc)
            prev = c
        self.first_close = candles[0].close_time_utc if candles else None

    def median_daily_quote_volume(self, t: datetime) -> Decimal | None:
        """
        Median daily ``sum(volume x close)`` over the last 30 complete UTC days before ``t``.

        Args:
            t (datetime): Decision time.

        Returns:
            Decimal | None: Median, or None if no complete day exists.
        """
        end = datetime(t.year, t.month, t.day, tzinfo=UTC).date()
        days = [end - timedelta(days=i) for i in range(1, LIQUIDITY_DAYS + 1)]
        vals = [self.daily[d] for d in days if d in self.daily]
        return median(vals) if vals else None

    def continuous_days(self, t: datetime) -> Decimal:
        """
        Days of continuous history up to ``t``; any gap restarts the count.

        Args:
            t (datetime): Decision time.

        Returns:
            Decimal: Days (0 if no data closed by ``t``).
        """
        if self.first_close is None or self.first_close > t:
            return Decimal(0)
        idx = bisect_right(self.segment_starts, t) - 1
        start = self.segment_starts[max(idx, 0)]
        return Decimal((t - start).total_seconds()) / Decimal(86400)


class EligibilityEvaluator:
    """Evaluates every in-scope instrument at a decision time."""

    def __init__(
        self,
        compiled: CompiledProfile,
        profile: TradingProfile,
        registry: Registry,
        history: dict[str, list[Candle]],
        venues: dict[str, str],
        timeframe_delta: timedelta,
    ) -> None:
        """
        Prepare the evaluator.

        Args:
            compiled (CompiledProfile): Compiled profile (thresholds).
            profile (TradingProfile): Trading profile (scope, exclusions).
            registry (Registry): Asset registry.
            history (dict[str, list[Candle]]): Candles per instrument.
            venues (dict[str, str]): Dataset venue per instrument.
            timeframe_delta (timedelta): Bar length.
        """
        self.compiled = compiled
        self.profile = profile
        self.registry = registry
        self.venues = venues
        self._hist = {k: _History(v, timeframe_delta) for k, v in history.items()}

    def _threshold(self, key: str) -> Decimal | str | None:
        """
        Read an effective eligibility threshold.

        Args:
            key (str): Key below ``eligibility.``.

        Returns:
            Decimal | str | None: Value or None if unresolved.
        """
        ev = self.compiled.effective.get(f"eligibility.{key}")
        if ev is None:
            return None
        return ev.value if isinstance(ev.value, str) else Decimal(ev.value)

    def evaluate_one(self, instrument_id: str, t: datetime) -> AssetEligibility:
        """
        Evaluate one instrument at ``t``.

        Args:
            instrument_id (str): Instrument.
            t (datetime): Decision time.

        Returns:
            AssetEligibility: Result with criterion outcomes.
        """
        inst = self.registry.instrument(instrument_id)
        asset = self.registry.asset(inst.base) if inst else None
        if inst is None or asset is None:
            return AssetEligibility(
                instrument_id=instrument_id,
                asset_id=instrument_id.split("-")[0],
                tier="unknown",
                eligible=False,
                criteria=[],
                reason="ASSET_NOT_SUPPORTED",
            )
        crit: list[CriterionOutcome] = []
        unresolved = False

        def add(name: str, ok: bool, obs: object, thr: object, why: str | None = None) -> None:
            crit.append(
                CriterionOutcome(
                    criterion=name,
                    passed=ok,
                    observed=None if obs is None else str(obs),
                    threshold=None if thr is None else str(thr),
                    reason=why,
                )
            )

        venue = self.venues.get(instrument_id, "")
        add("support", self.registry.has_mapping(instrument_id, venue), venue, None)
        excluded = asset.blocked or asset.asset_id in self.profile.universe.disallowed_assets
        add("explicit_exclusion", not excluded, "blocked" if excluded else "ok", None)
        hist = self._hist.get(instrument_id)
        for name, key, observed in (
            (
                "liquidity",
                f"liquidity.min_by_tier.{asset.tier}",
                hist.median_daily_quote_volume(t) if hist else None,
            ),
            (
                "data_history",
                f"data_history.min_by_tier.{asset.tier}",
                hist.continuous_days(t) if hist else Decimal(0),
            ),
        ):
            thr = self._threshold(key)
            if thr is None or isinstance(thr, str):
                unresolved = True
                add(name, False, observed, None, UNRESOLVED)
            else:
                add(name, observed is not None and observed >= thr, observed, thr)
        spread = self._threshold("spread.when_no_spread_data")
        if spread is None:
            unresolved = True
            add("spread", False, "no_spread_data", None, UNRESOLVED)
        else:
            # Reason: M1 has no spread provider; only an explicit not_applicable passes.
            add("spread", spread == "not_applicable", "no_spread_data", spread)
        eligible = all(c.passed for c in crit)
        reason = UNRESOLVED if unresolved else (None if eligible else "CRITERIA_FAILED")
        return AssetEligibility(
            instrument_id=instrument_id,
            asset_id=asset.asset_id,
            tier=asset.tier,
            eligible=eligible,
            criteria=crit,
            reason=reason,
        )

    def evaluate(self, t: datetime, snapshot_id: str) -> UniverseSnapshot:
        """
        Evaluate all in-scope instruments.

        Args:
            t (datetime): Decision time.
            snapshot_id (str): Universe snapshot ID.

        Returns:
            UniverseSnapshot: Snapshot.
        """
        assets = {i: self.evaluate_one(i, t) for i in self.profile.universe.instruments_in_scope}
        return UniverseSnapshot(
            schema_version="1.0.0",
            universe_snapshot_id=snapshot_id,
            as_of_utc=t,
            assets=dict(sorted(assets.items())),
        )
