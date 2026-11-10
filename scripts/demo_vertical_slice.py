"""One-command M1 demo (handoff §10.2). Works offline; needs no secrets.

Usage:
    uv run python scripts/demo_vertical_slice.py

Runs (owner decisions of 2026-11-01 applied): runnable validation, paper refusal (no
activation record yet), refusal of experiment values that would override approved values,
synthetic BTC/ETH data, the vertical-slice backtest on the approved configs, report display,
and journal verification.
"""

from __future__ import annotations

import re
import subprocess
import sys

PROFILE = "configs/profiles/balanced-paper.yaml"
EXPERIMENT = "experiments/EXP-2026-001-vertical-slice.yaml"


def trader(*args: str, expect: int = 0) -> str:
    """
    Run a ``trader`` command and check its exit code.

    Args:
        *args (str): CLI arguments.
        expect (int): Expected exit code.

    Returns:
        str: Captured stdout.

    Raises:
        SystemExit: If the exit code differs from ``expect``.
    """
    cmd = [sys.executable, "-m", "trader.cli.main", *args]
    print(f"\n$ trader {' '.join(args)}   (expect exit {expect})", flush=True)
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    print(res.stdout.rstrip())
    if res.returncode != expect:
        print(res.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"unexpected exit code {res.returncode} (expected {expect})")
    return res.stdout


def synth(instrument: str, seed: str, start_price: str) -> str:
    """
    Create a 2023-2025 synthetic 4h dataset.

    Args:
        instrument (str): Instrument ID.
        seed (str): RNG seed.
        start_price (str): First open price.

    Returns:
        str: Dataset ID.
    """
    out = trader("data", "synth", "--instrument", instrument, "--timeframe", "4h",
                 "--start", "2023-01-01T00:00:00Z", "--end", "2026-01-01T00:00:00Z",
                 "--seed", seed, "--start-price", start_price)  # fmt: skip
    return out.strip().splitlines()[-1]


def main() -> None:
    """Run the demo steps in order."""
    trader("version")
    # Owner decisions of 2026-11-01 are applied: the shipped profile is runnable as is.
    trader("profile", "validate", PROFILE, "--environment", "backtest")
    # Paper needs an active profile with an activation record (BL-028, not built yet).
    trader("profile", "validate", PROFILE, "--environment", "paper", expect=2)
    # EXP-2026-001 targets values the owner has now approved, so RP-12 rejects it.
    trader("profile", "validate", PROFILE, "--environment", "backtest",
           "--experiment", EXPERIMENT, expect=2)  # fmt: skip
    # The approved universe (UD-06 B): Core BTC/ETH, Major SOL/XRP, Speculative SUI.
    ids = [
        synth(i, seed, px)
        for i, seed, px in (
            ("BTC-USD", "42", "30000"),
            ("ETH-USD", "43", "2000"),
            ("SOL-USD", "44", "90"),
            ("XRP-USD", "45", "1.2"),
            ("SUI-USD", "46", "0.9"),
        )
    ]
    btc = ids[0]
    trader("data", "validate", btc)
    trader("data", "list")
    # Evaluation starts after the 365 days of history required by UD-18 (approved).
    out = trader("backtest", "run", "--profile", PROFILE, "--datasets", ",".join(ids),
                 "--strategy", "sma_trend", "--timeframe", "4h",
                 "--start", "2024-01-01T00:00:00Z")  # fmt: skip
    m = re.search(r"run_id: (\S+)", out)
    assert m, "no run_id printed"
    run_id = m.group(1)
    trader("report", "show", run_id)
    trader("journal", "verify", run_id)
    trader("killswitch", "status")
    report = re.search(r"report: (\S+)", out)
    print(f"\nDemo complete. Report: {report.group(1) if report else '?'}")


if __name__ == "__main__":
    main()
