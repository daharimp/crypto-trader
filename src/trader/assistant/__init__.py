"""Review assistant extensions (ADR-045): per-trade analysis, daily summaries, drawdown alerts.

Reports only. Nothing in this package edits a config, places an order, or touches a running
session; it reads saved state and logs and writes ``data/reports/``.
"""
