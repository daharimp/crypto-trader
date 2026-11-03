"""Strategy comparison across consecutive windows, cost scenarios, and a random control.

An edge is credible only if it holds across separate periods, survives realistic costs, beats
simply holding the universe, and beats random entry timing under the same risk rules. The
random-entry runs are matched to the reference strategy's trade frequency and holding time
in each window, so the comparison isolates timing skill.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

import yaml

from trader.backtest.runner import run_backtest
from trader.common.paths import data_root

STEP = timedelta(hours=4)


@dataclass
class CompareConfig:
    """What to compare."""

    profile: Path
    datasets: list[str]
    start: datetime
    end: datetime
    strategies: list[str] = field(default_factory=lambda: ["sma_trend"])
    cost_scenarios: list[str] = field(default_factory=lambda: ["base"])
    windows: int = 2
    random_seeds: int = 10
    reference_strategy: str = "sma_trend"
    eligibility_datasets: list[str] | None = None
    configs_root: Path = Path("configs")
    timeframe: str = "4h"


def window_bounds(start: datetime, end: datetime, n: int) -> list[tuple[datetime, datetime]]:
    """
    Split ``[start, end]`` into ``n`` consecutive windows aligned to 4h bar closes.

    Args:
        start (datetime): First decision time.
        end (datetime): Last decision time.
        n (int): Number of windows (>= 1).

    Returns:
        list[tuple[datetime, datetime]]: Window bounds.

    Raises:
        ValueError: If the range is too short for ``n`` windows of at least one week.
    """
    bars = int((end - start) / STEP)
    if n < 1 or bars // n < 42:
        raise ValueError(f"range of {bars} bars is too short for {n} windows of >= 7 days")
    size = bars // n
    out = []
    for k in range(n):
        s = start + k * size * STEP
        e = end if k == n - 1 else s + size * STEP
        out.append((s, e))
    return out


def _metrics(run_id: str, exit_code: int) -> dict[str, Any]:
    """
    Read the headline numbers of one backtest report.

    Args:
        run_id (str): Run ID.
        exit_code (int): Backtest exit code.

    Returns:
        dict[str, Any]: Metrics (``ok`` False if the run failed).
    """
    path = data_root() / "reports" / run_id / "report.json"
    if exit_code != 0 or not path.exists():
        return {"ok": False, "run_id": run_id, "exit_code": exit_code}
    r = json.loads(path.read_text())
    s, b = r["strategy"]["metrics"], r["benchmarks"]

    def f(x: Any) -> float:
        return float(x) if x not in (None, "") else 0.0

    hold = b.get("bm_ew_universe") or b.get("bm_ew_btc_eth") or {}
    return {
        "ok": True,
        "run_id": run_id,
        "return": f(s["total_return"]),
        "sharpe": f(s["sharpe_like"]),
        "max_dd": f(s["max_drawdown"]),
        "trades": int(s["closed_trades"]),
        "fees": f(s["fees_usd"]),
        "hold_hours": f(s["avg_holding_hours"]),
        "hold_return": f(hold.get("total_return")),
        "btc_return": f(b.get("bm_bh_btc", {}).get("total_return")),
        "rejections": r["trading"]["rejections_by_reason"],
    }


class Comparison:
    """Runs the grid and summarises it."""

    def __init__(self, cfg: CompareConfig, work_dir: Path) -> None:
        """
        Prepare a comparison.

        Args:
            cfg (CompareConfig): Configuration.
            work_dir (Path): Scratch directory (a private copy of the configs lives here).
        """
        self.cfg = cfg
        self.root = work_dir / "configs"
        if self.root.exists():
            shutil.rmtree(self.root)
        shutil.copytree(cfg.configs_root, self.root)
        self.runs: list[dict[str, Any]] = []

    def _run(self, strategy: str, cost: str, s: datetime, e: datetime) -> dict[str, Any]:
        """
        One backtest.

        Args:
            strategy (str): Strategy ID.
            cost (str): Cost scenario.
            s (datetime): Window start.
            e (datetime): Window end.

        Returns:
            dict[str, Any]: Metrics.
        """
        res = run_backtest(
            self.cfg.profile,
            self.cfg.datasets,
            strategy,
            self.cfg.timeframe,
            None,
            cost,
            s,
            e,
            self.root,
            command=f"research compare {strategy} {cost}",
            eligibility_datasets=self.cfg.eligibility_datasets,
        )
        return _metrics(res.run_id, res.exit_code)

    def _set_random(self, seed: int, ref: dict[str, Any], bars: int) -> None:
        """
        Match the random control to the reference run's frequency and holding time.

        Args:
            seed (int): Seed.
            ref (dict[str, Any]): Reference strategy metrics in the same window and cost.
            bars (int): Bars in the window.
        """
        n_inst = max(1, len({d for d in self.cfg.datasets}))
        trades = max(ref.get("trades", 0), 1)
        hold_bars = max(ref.get("hold_hours", 0.0) / 4.0, 1.0)
        p_entry = min(max(trades / (bars * n_inst), 1e-4), 0.5)
        p_exit = min(max(1.0 / hold_bars, 1e-4), 0.9)
        path = self.root / "strategies" / "random_entry.yaml"
        entry = yaml.safe_load(path.read_text())
        entry["parameters"] = {
            "seed": seed,
            "p_entry": round(p_entry, 6),
            "p_exit": round(p_exit, 6),
        }
        path.write_text(yaml.safe_dump(entry, sort_keys=False))

    def run(self) -> dict[str, Any]:
        """
        Run every strategy x cost x window, plus matched random controls.

        Returns:
            dict[str, Any]: Runs and summary.
        """
        cfg = self.cfg
        for w, (s, e) in enumerate(window_bounds(cfg.start, cfg.end, cfg.windows), start=1):
            bars = int((e - s) / STEP)
            for cost in cfg.cost_scenarios:
                refs: dict[str, dict[str, Any]] = {}
                for strat in cfg.strategies:
                    m = self._run(strat, cost, s, e)
                    refs[strat] = m
                    self.runs.append(
                        {
                            "window": w,
                            "start": s.isoformat(),
                            "end": e.isoformat(),
                            "cost": cost,
                            "strategy": strat,
                            **m,
                        }
                    )
                ref = refs.get(cfg.reference_strategy, {})
                for seed in range(cfg.random_seeds):
                    self._set_random(seed, ref, bars)
                    m = self._run("random_entry", cost, s, e)
                    self.runs.append(
                        {
                            "window": w,
                            "start": s.isoformat(),
                            "end": e.isoformat(),
                            "cost": cost,
                            "strategy": "random_entry",
                            "seed": seed,
                            **m,
                        }
                    )
        return {"config": _config_json(cfg), "runs": self.runs, "summary": summarise(self.runs)}


def summarise(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Per strategy and cost: consistency across windows and rank against random timing.

    Args:
        runs (list[dict[str, Any]]): Run rows.

    Returns:
        list[dict[str, Any]]: Summary rows.
    """
    ok = [r for r in runs if r.get("ok")]
    out = []
    keys = sorted({(r["strategy"], r["cost"]) for r in ok if r["strategy"] != "random_entry"})
    for strat, cost in keys:
        rows = [r for r in ok if r["strategy"] == strat and r["cost"] == cost]
        beat_rand = []
        for r in rows:
            rand = [
                x["return"]
                for x in ok
                if x["strategy"] == "random_entry"
                and x["cost"] == cost
                and x["window"] == r["window"]
            ]
            if rand:
                beat_rand.append(sum(1 for x in rand if x < r["return"]) / len(rand))
        out.append(
            {
                "strategy": strat,
                "cost": cost,
                "windows": len(rows),
                "median_return": median(r["return"] for r in rows),
                "mean_return": mean(r["return"] for r in rows),
                "share_positive": sum(r["return"] > 0 for r in rows) / len(rows),
                "share_beat_hold": sum(r["return"] > r["hold_return"] for r in rows) / len(rows),
                "mean_sharpe": mean(r["sharpe"] for r in rows),
                "worst_dd": max(r["max_dd"] for r in rows),
                "trades": sum(r["trades"] for r in rows),
                "fees": sum(r["fees"] for r in rows),
                "median_hold_return": median(r["hold_return"] for r in rows),
                "pct_random_beaten": mean(beat_rand) if beat_rand else None,
            }
        )
    rand_rows = [r for r in ok if r["strategy"] == "random_entry"]
    for cost in sorted({r["cost"] for r in rand_rows}):
        rr = [r for r in rand_rows if r["cost"] == cost]
        out.append(
            {
                "strategy": "random_entry (all seeds)",
                "cost": cost,
                "windows": len(rr),
                "median_return": median(r["return"] for r in rr),
                "mean_return": mean(r["return"] for r in rr),
                "share_positive": sum(r["return"] > 0 for r in rr) / len(rr),
                "share_beat_hold": sum(r["return"] > r["hold_return"] for r in rr) / len(rr),
                "mean_sharpe": mean(r["sharpe"] for r in rr),
                "worst_dd": max(r["max_dd"] for r in rr),
                "trades": sum(r["trades"] for r in rr),
                "fees": sum(r["fees"] for r in rr),
                "median_hold_return": median(r["hold_return"] for r in rr),
                "pct_random_beaten": None,
            }
        )
    return out


def _config_json(cfg: CompareConfig) -> dict[str, Any]:
    """
    JSON-friendly configuration.

    Args:
        cfg (CompareConfig): Configuration.

    Returns:
        dict[str, Any]: Configuration.
    """
    d = dict(cfg.__dict__)
    return {k: (str(v) if isinstance(v, (Path, datetime)) else v) for k, v in d.items()}


def render_markdown(result: dict[str, Any]) -> str:
    """
    Summary table in Markdown.

    Args:
        result (dict[str, Any]): Output of :meth:`Comparison.run`.

    Returns:
        str: Markdown.
    """

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:+.1f}%"

    def share(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.0f}%"

    lines = [
        "| Strategy | Costs | Windows | Median return | Median hold-all | Beat hold-all |"
        " Positive | Beat random | Mean Sharpe | Worst DD | Trades | Fees |",
        "|---" * 12 + "|",
    ]
    for r in result["summary"]:
        lines.append(
            f"| {r['strategy']} | {r['cost']} | {r['windows']} | {pct(r['median_return'])} | "
            f"{pct(r['median_hold_return'])} | {share(r['share_beat_hold'])} | "
            f"{share(r['share_positive'])} | {share(r['pct_random_beaten'])} | "
            f"{r['mean_sharpe']:.2f} | {r['worst_dd'] * 100:.1f}% | {r['trades']} | "
            f"${r['fees']:.2f} |"
        )
    failed = [r for r in result["runs"] if not r.get("ok")]
    if failed:
        lines.append(
            f"\n{len(failed)} run(s) failed: "
            + ", ".join(
                f"{r['strategy']}/{r['cost']}/w{r['window']} (exit {r['exit_code']})"
                for r in failed
            )
        )
    return "\n".join(lines) + "\n"


def utc(text: str) -> datetime:
    """
    Parse ``YYYY-MM-DDTHH:MM:SSZ``.

    Args:
        text (str): Timestamp.

    Returns:
        datetime: UTC datetime.
    """
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
