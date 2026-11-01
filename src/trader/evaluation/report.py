"""Report writer: JSON and Markdown with disclaimer and provenance banner (§7.12)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from trader.common.canonical import to_canonical_obj
from trader.domain.compiled import CompiledProfile
from trader.domain.enums import Provenance

DISCLAIMER = (
    "Simulated results on historical data. Not a forecast. "
    "Profitability is not guaranteed or implied."
)
REPORT_SCHEMA_VERSION = "1.0.0"


def non_approved_values(compiled: CompiledProfile) -> list[dict[str, str]]:
    """
    List every effective value that is not owner-approved.

    Args:
        compiled (CompiledProfile): Compiled profile.

    Returns:
        list[dict[str, str]]: Field, value, provenance, ref.
    """
    return [
        {
            "field": k,
            "value": json.dumps(to_canonical_obj(v.value), sort_keys=True),
            "provenance": v.provenance.value,
            "ref": v.ref,
        }
        for k, v in sorted(compiled.effective.items())
        if v.provenance != Provenance.APPROVED
    ]


def comparison(
    strategy: dict[str, Any], benchmarks: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    """
    Excess total return and CAGR of the strategy over each benchmark.

    Args:
        strategy (dict[str, Any]): Strategy metrics.
        benchmarks (dict[str, dict[str, Any]]): Benchmark metrics.

    Returns:
        list[dict[str, str]]: Comparison rows.
    """
    out = []
    for name, m in benchmarks.items():
        out.append(
            {
                "benchmark": name,
                "excess_total_return": format(
                    (Decimal(strategy["total_return"]) - Decimal(m["total_return"])), "f"
                ),
                "excess_cagr": format(Decimal(strategy["cagr"]) - Decimal(m["cagr"]), "f"),
            }
        )
    return out


def render_markdown(report: dict[str, Any]) -> str:
    """
    Render the Markdown report.

    Args:
        report (dict[str, Any]): Report JSON.

    Returns:
        str: Markdown text.
    """
    prov = report["provenance"]
    lines = [
        f"> **{report['disclaimer']}**",
        "",
        f"# Backtest report `{report['run_metadata']['run_id']}`",
        "",
        "## Values used that are NOT owner-approved",
        "",
        "| Field | Value | Provenance | Ref |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| `{v['field']}` | `{v['value']}` | {v['provenance']} | {v['ref']} |"
        for v in prov["non_approved_values"]
    ]
    lines += [
        "",
        f"Experiment: `{prov['experiment_id']}` · config hash `{prov['config_hash']}` · "
        f"profile `{prov['trading_profile']['id']}` v{prov['trading_profile']['version']} · "
        f"risk `{prov['risk_profile']['id']}` v{prov['risk_profile']['version']}",
        "",
        "## Comparison with benchmarks",
        "",
        "| Benchmark | Excess total return | Excess CAGR |",
        "|---|---|---|",
    ]
    lines += [
        f"| {c['benchmark']} | {c['excess_total_return']} | {c['excess_cagr']} |"
        for c in report["comparison"]
    ]
    keys = [
        "final_equity_usd",
        "total_return",
        "cagr",
        "max_drawdown",
        "volatility",
        "sharpe_like",
        "sortino_like",
        "calmar",
        "fees_usd",
        "slippage_cost_usd",
    ]
    cols = {"strategy": report["strategy"]["metrics"], **report["benchmarks"]}
    lines += [
        "",
        "## Metrics",
        "",
        "| Metric | " + " | ".join(cols) + " |",
        "|---" * (len(cols) + 1) + "|",
    ]
    for k in keys:
        lines.append(f"| {k} | " + " | ".join(str(m.get(k, "")) for m in cols.values()) + " |")
    tr = report["trading"]
    lines += [
        "",
        "## Trading",
        "",
        f"- Order intents: {tr['order_intents']}",
        f"- Fills: {tr['fills']}",
        f"- Closed trades: {tr['closed_trades']}",
        f"- Fees (USD): {tr['fees_usd']}",
        f"- Slippage cost (USD): {tr['slippage_cost_usd']}",
        "",
        "### Rejections by reason code",
        "",
        "| Reason | Count |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sorted(tr["rejections_by_reason"].items())] or []
    if not tr["rejections_by_reason"]:
        lines.append("| (none) | 0 |")
    d = report["data"]
    lines += [
        "",
        "## Data and costs",
        "",
        f"- Datasets: {', '.join(d['datasets'])}",
        f"- Timeframe: {d['timeframe']}",
        f"- Evaluation window: {d['evaluation_start_utc']} to {d['evaluation_end_utc']}",
        f"- Costs: {json.dumps(report['costs'], sort_keys=True)}",
        f"- Journal root: `{report['journal']['root_hash']}` "
        f"({report['journal']['event_count']} events)",
        "",
    ]
    return "\n".join(lines)


def write_report(report: dict[str, Any], out_dir: Path) -> Path:
    """
    Write ``report.json`` and ``report.md``.

    Args:
        report (dict[str, Any]): Report.
        out_dir (Path): ``data/reports/<run_id>``.

    Returns:
        Path: Path of ``report.md``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    md = out_dir / "report.md"
    md.write_text(render_markdown(report))
    return md
