"""One-command M1 demo (handoff §10.2). Works offline; needs no secrets.

Usage:
    uv run python scripts/demo_vertical_slice.py

Runs: fail-closed validation, paper refusal, runnable validation, synthetic BTC/ETH data,
the vertical-slice backtest with EXP-2026-001, report display, and journal verification.
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


def main() -> None:
    """Run the demo steps in order."""
    trader("version")
    trader("profile", "validate", PROFILE, "--environment", "backtest", expect=3)
    trader(
        "profile",
        "validate",
        PROFILE,
        "--environment",
        "paper",
        "--experiment",
        EXPERIMENT,
        expect=2,
    )
    trader("profile", "validate", PROFILE, "--environment", "backtest", "--experiment", EXPERIMENT)
    btc = (
        trader(
            "data",
            "synth",
            "--instrument",
            "BTC-USD",
            "--timeframe",
            "4h",
            "--start",
            "2023-01-01T00:00:00Z",
            "--end",
            "2026-01-01T00:00:00Z",
            "--seed",
            "42",
            "--start-price",
            "30000",
        )
        .strip()
        .splitlines()[-1]
    )
    eth = (
        trader(
            "data",
            "synth",
            "--instrument",
            "ETH-USD",
            "--timeframe",
            "4h",
            "--start",
            "2023-01-01T00:00:00Z",
            "--end",
            "2026-01-01T00:00:00Z",
            "--seed",
            "43",
            "--start-price",
            "2000",
        )
        .strip()
        .splitlines()[-1]
    )
    trader("data", "validate", btc)
    trader("data", "list")
    out = trader(
        "backtest",
        "run",
        "--profile",
        PROFILE,
        "--experiment",
        EXPERIMENT,
        "--datasets",
        f"{btc},{eth}",
        "--strategy",
        "sma_trend",
        "--timeframe",
        "4h",
        "--start",
        "2024-01-01T00:00:00Z",
    )
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
