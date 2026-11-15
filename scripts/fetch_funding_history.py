"""Download public hourly perpetual-futures funding rates to CSV (EXP-2026-014).

Research data only: no account, no keys, public endpoints. Output has one row per hour:
``hour_start_utc,rate`` where ``rate`` is the fraction of position size paid by longs to
shorts for that hour (negative: shorts pay longs). Hours the venue did not publish are
simply absent; nothing is filled in.

Timestamp conventions (fixed in research/EXP-2026-014-plan.md): a Deribit or Hyperliquid
record stamped T covers the hour ending at T; a Kraken record stamped T covers the hour
starting at T.

Usage:
    uv run python scripts/fetch_funding_history.py deribit BTC data/funding/deribit_btc.csv
    uv run python scripts/fetch_funding_history.py hyperliquid SOL data/funding/hyperliquid_sol.csv
    uv run python scripts/fetch_funding_history.py kraken ETH data/funding/kraken_eth.csv
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HOUR = timedelta(hours=1)
DERIBIT = {"BTC": "BTC-PERPETUAL", "ETH": "ETH-PERPETUAL", "SOL": "SOL_USDC-PERPETUAL"}
KRAKEN = {"BTC": "PF_XBTUSD", "ETH": "PF_ETHUSD", "SOL": "PF_SOLUSD"}
DERIBIT_URL = "https://www.deribit.com/api/v2/public/get_funding_rate_history?"
HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
KRAKEN_URL = "https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?symbol="
# Reason: earlier than either venue's first perpetual, so paging starts before any data.
EPOCH_START = datetime(2018, 1, 1, tzinfo=UTC)


def _request(url: str, body: dict[str, Any] | None = None) -> Any:
    """GET (or POST JSON when ``body`` is given) with retries; returns the parsed JSON."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": "trader-research", "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers)  # noqa: S310
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
                return json.loads(r.read())
        except OSError:
            time.sleep(2**attempt)
    raise SystemExit(f"failed: {url}")


def _hour(ms: float) -> datetime:
    """Nearest whole hour (venues stamp a few milliseconds after the boundary)."""
    return datetime.fromtimestamp(round(ms / 3_600_000) * 3600, tz=UTC)


def fetch_deribit(coin: str) -> dict[datetime, str]:
    """
    Hourly funding for a Deribit perpetual, from its first record to now.

    Args:
        coin (str): BTC, ETH, or SOL.

    Returns:
        dict[datetime, str]: hour start -> rate for that hour (``interest_1h``).
    """
    out: dict[datetime, str] = {}
    cur, end = EPOCH_START, datetime.now(UTC)
    # Reason: the endpoint caps the rows per call, so the range is paged in 20-day windows
    # (480 hours) and each window's row count is checked against that cap.
    step = timedelta(days=20)
    while cur < end:
        query = urllib.parse.urlencode(
            {
                "instrument_name": DERIBIT[coin],
                "start_timestamp": int(cur.timestamp() * 1000),
                "end_timestamp": int((cur + step).timestamp() * 1000),
            }
        )
        rows = _request(DERIBIT_URL + query)["result"]
        if len(rows) > 481:
            raise SystemExit(f"deribit returned {len(rows)} rows for a 480-hour window")
        for row in rows:
            out[_hour(row["timestamp"]) - HOUR] = repr(float(row["interest_1h"]))
        cur += step
        time.sleep(0.1)
    return out


def fetch_hyperliquid(coin: str) -> dict[datetime, str]:
    """
    Hourly funding for a Hyperliquid perpetual, from its first record to now.

    Args:
        coin (str): Hyperliquid coin name, e.g. BTC or DOGE.

    Returns:
        dict[datetime, str]: hour start -> rate for that hour.
    """
    out: dict[datetime, str] = {}
    start = int(EPOCH_START.timestamp() * 1000)
    while True:
        rows = _request(
            HYPERLIQUID_URL, {"type": "fundingHistory", "coin": coin, "startTime": start}
        )
        if not rows:
            break
        for row in rows:
            out[_hour(row["time"]) - HOUR] = repr(float(row["fundingRate"]))
        # Reason: the endpoint returns at most 500 rows, oldest first; continue after the last.
        nxt = int(rows[-1]["time"]) + 1
        if nxt <= start:
            break
        start = nxt
        time.sleep(0.3)
    return out


def fetch_kraken(coin: str) -> dict[datetime, str]:
    """
    Hourly funding for a Kraken Futures perpetual (the venue publishes about 12 months).

    Args:
        coin (str): BTC, ETH, or SOL.

    Returns:
        dict[datetime, str]: hour start -> rate for that hour (``relativeFundingRate``).
    """
    rows = _request(KRAKEN_URL + KRAKEN[coin])["rates"]
    return {
        _hour(datetime.fromisoformat(r["timestamp"]).timestamp() * 1000): repr(
            float(r["relativeFundingRate"])
        )
        for r in rows
    }


SOURCES = {"deribit": fetch_deribit, "hyperliquid": fetch_hyperliquid, "kraken": fetch_kraken}


def main(argv: list[str]) -> int:
    """Fetch one source and coin and write the CSV."""
    # Reason: Hyperliquid lists many coins; Deribit and Kraken symbols are mapped above.
    known = len(argv) == 4 and (
        argv[2] in DERIBIT or (argv[1] == "hyperliquid" and argv[2].isalnum())
    )
    if not known or argv[1] not in SOURCES:
        print(__doc__)
        return 2
    rates = SOURCES[argv[1]](argv[2])
    # Reason: the current hour's rate is not final until the hour ends.
    cutoff = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    rows = sorted((t, r) for t, r in rates.items() if t + HOUR <= cutoff)
    if not rows:
        raise SystemExit("no funding rows returned")
    out = Path(argv[3])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hour_start_utc", "rate"])
        for t, r in rows:
            w.writerow([t.isoformat(), r])
    print(
        f"wrote {len(rows)} hours to {out}: {rows[0][0].isoformat()} to {rows[-1][0].isoformat()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
