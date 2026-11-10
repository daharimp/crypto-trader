"""Download public Coinbase candles and write 4h (or 1h) CSV for ``trader data import``.

Research data only: no account, no keys, plain HTTPS GET. Coinbase serves at most 300
candles per request, so the range is paged. 4h bars are built from four complete 1h bars
aligned to 00:00, 04:00, ... UTC; a 4h bucket missing any hour is dropped (the dataset
quality checks then report the gap rather than hiding it).

Usage:
    uv run python scripts/fetch_coinbase_history.py SOL-USD 800 data/raw/sol_usd_4h.csv
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

BASE = "https://api.exchange.coinbase.com/products/{p}/candles?granularity=3600&start={s}&end={e}"


def fetch_hourly(product: str, days: int) -> dict[datetime, tuple[Decimal, ...]]:
    """
    Fetch hourly candles for the last ``days`` days.

    Args:
        product (str): Coinbase product, e.g. ``SOL-USD``.
        days (int): Days of history.

    Returns:
        dict[datetime, tuple[Decimal, ...]]: open time -> (open, high, low, close, volume).
    """
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    cur = end - timedelta(days=days)
    out: dict[datetime, tuple[Decimal, ...]] = {}
    while cur < end:
        nxt = min(cur + timedelta(hours=300), end)
        url = BASE.format(p=product, s=cur.isoformat(), e=nxt.isoformat())
        req = urllib.request.Request(url, headers={"User-Agent": "trader-research"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                    rows = json.loads(r.read())
                break
            except OSError:
                time.sleep(2**attempt)
        else:
            raise SystemExit(f"failed: {url}")
        # Coinbase row: [time_s, low, high, open, close, volume]
        for t, lo, hi, op, cl, vol in rows:
            ts = datetime.fromtimestamp(int(t), tz=UTC)
            if ts < end:  # Reason: the current hour is still forming.
                out[ts] = tuple(Decimal(str(x)) for x in (op, hi, lo, cl, vol))
        cur = nxt
        time.sleep(0.2)  # Reason: stay well under the public rate limit.
    return out


def to_4h(
    hourly: dict[datetime, tuple[Decimal, ...]],
) -> list[tuple[datetime, tuple[Decimal, ...]]]:
    """
    Aggregate complete groups of four hourly bars into 4h bars.

    Args:
        hourly (dict): Hourly bars.

    Returns:
        list: (open time, (open, high, low, close, volume)), oldest first.
    """
    bars = []
    starts = sorted({t.replace(hour=t.hour - t.hour % 4) for t in hourly})
    for s in starts:
        hs = [hourly.get(s + timedelta(hours=i)) for i in range(4)]
        if any(h is None for h in hs):
            continue
        o = hs[0][0]  # type: ignore[index]
        hi = max(h[1] for h in hs)  # type: ignore[index]
        lo = min(h[2] for h in hs)  # type: ignore[index]
        c = hs[3][3]  # type: ignore[index]
        v = sum((h[4] for h in hs), Decimal(0))  # type: ignore[index]
        bars.append((s, (o, hi, lo, c, v)))
    return bars


def main() -> None:
    """Fetch, aggregate, and write the CSV."""
    product, days, out = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
    tf = sys.argv[4] if len(sys.argv) > 4 else "4h"
    hourly = fetch_hourly(product, days)
    bars = to_4h(hourly) if tf == "4h" else sorted(hourly.items())
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time_utc", "open", "high", "low", "close", "volume"])
        for t, (o, h, lo, c, v) in bars:
            w.writerow([t.strftime("%Y-%m-%dT%H:%M:%SZ"), o, h, lo, c, v])
    print(f"{product}: {len(hourly)} hourly -> {len(bars)} {tf} bars -> {out}")


if __name__ == "__main__":
    main()
