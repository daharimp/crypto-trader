"""Deterministic synthetic candle generator (handoff §7.5).

All constants are test-fixture values with no market meaning.
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal

import numpy as np

from trader.common.clock import ensure_utc, is_aligned, timeframe_delta
from trader.domain.candles import Candle

# (mu, sigma) of the per-4h-bar log return for each regime (fixture constants).
_REGIMES = {"up": (0.0015, 0.012), "down": (-0.0015, 0.015), "flat": (0.0, 0.008)}
_ORDER = ["up", "down", "flat"]
_STAY = 0.98


def _q(x: float, n: int) -> Decimal:
    """
    Quantize a float to ``n`` decimals via its text form.

    Args:
        x (float): Value.
        n (int): Decimals.

    Returns:
        Decimal: Quantized value.
    """
    return Decimal(str(round(x, n)))


class SyntheticCandleProvider:
    """Three-state Markov regime random walk using ``numpy`` PCG64."""

    provider_id = "synthetic"
    venue_id = "sim"

    def __init__(
        self, seed: int, start_price: Decimal, daily_quote_volume_usd: Decimal = Decimal("1e9")
    ) -> None:
        """
        Configure the generator.

        Args:
            seed (int): RNG seed.
            start_price (Decimal): First open price.
            daily_quote_volume_usd (Decimal): Target daily quote volume.
        """
        self.seed = seed
        self.start_price = start_price
        self.daily_quote_volume_usd = daily_quote_volume_usd

    def fetch_candles(
        self, instrument_id: str, timeframe: str, start_utc: datetime, end_utc: datetime
    ) -> list[Candle]:
        """
        Generate candles for ``[start_utc, end_utc)``.

        Args:
            instrument_id (str): Instrument (labels only).
            timeframe (str): Timeframe.
            start_utc (datetime): Aligned start.
            end_utc (datetime): End (exclusive).

        Returns:
            list[Candle]: Deterministic candles.

        Raises:
            ValueError: If ``start_utc`` is not aligned to the timeframe.
        """
        start, end = ensure_utc(start_utc), ensure_utc(end_utc)
        if not is_aligned(start, timeframe):
            raise ValueError("start is not aligned to the timeframe")
        delta = timeframe_delta(timeframe)
        bar_hours = delta.total_seconds() / 3600
        scale = math.sqrt(bar_hours / 4)
        bars_per_day = 24 / bar_hours
        rng = np.random.Generator(np.random.PCG64(self.seed))
        state = "flat"
        price = self.start_price
        out: list[Candle] = []
        t = start
        while t < end:
            # Reason: draws happen in a fixed order per bar so a seed reproduces exactly.
            u = rng.random()
            if u >= _STAY:
                others = [s for s in _ORDER if s != state]
                state = others[0] if u < _STAY + (1 - _STAY) / 2 else others[1]
            mu, sigma = _REGIMES[state]
            mu, sigma = mu * scale, sigma * scale
            r = rng.normal(mu, sigma)
            hi_n = abs(rng.normal(0, sigma / 2))
            lo_n = abs(rng.normal(0, sigma / 2))
            vol_n = rng.lognormal(0, 0.3)
            o = float(price)
            c = _q(o * math.exp(r), 2)
            hi = _q(max(o, float(c)) * math.exp(hi_n), 2)
            lo = _q(min(o, float(c)) * math.exp(-lo_n), 2)
            hi, lo = max(hi, price, c), min(lo, price, c)
            vol = _q(float(self.daily_quote_volume_usd) / bars_per_day / float(c) * vol_n, 6)
            out.append(
                Candle(
                    open_time_utc=t,
                    close_time_utc=t + delta,
                    open=price,
                    high=hi,
                    low=lo,
                    close=c,
                    volume=vol,
                )
            )
            price = c
            t = t + delta
        return out
