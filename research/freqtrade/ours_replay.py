"""EXP-2026-027: our paper engine on the same windows as the freqtrade runs (no borrow).

Needs ``research/exp023_lib.py`` (the EXP-2026-023 replay harness) next to it or on the path.
Usage: uv run python research/freqtrade/ours_replay.py <candle dir> <cache dir> <out dir>
"""

import dataclasses
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent)]
import exp023_lib as lib  # noqa: E402

feed = lib.build_feed(Path(sys.argv[1]), "4h", Path(sys.argv[2]))
params, _ = lib.account("main", Path(__file__).parents[2] / "configs")
W = {
    "dev": lib.WINDOWS["dev"],
    "hold": (lib.WINDOWS["hold"][0], datetime(2026, 11, 21, tzinfo=UTC)),
}
for label, change in {"ladder": {}, "noladder": {"take_profits": None}}.items():
    p = dataclasses.replace(params, borrow_rate_pct_per_hour=Decimal(0), **change)
    for w, (a, b) in W.items():
        r = lib.run(p, feed, a, b)
        json.dump(
            {"events": r.events, "daily": {str(k): v for k, v in r.daily_equity.items()}},
            open(Path(sys.argv[3]) / f"ours-{label}-{w}.json", "w"),
            default=str,
        )
