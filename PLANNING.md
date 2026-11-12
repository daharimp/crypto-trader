# PLANNING

## Goal

A research and engineering system for AI-assisted crypto **paper** trading (D-01) whose
objective is to "balance strong returns with consistent performance and controlled drawdown"
(D-05), with simulated $2,500 capital (D-04), and never assuming guaranteed profit (D-07).

## Current milestone

**M1: V1 vertical slice**, done. **Owner decisions** UD-01..UD-21 resolved (2026-11-01).
**Live trading on Kraken** (ADR-023): forward paper/live sessions, activation, live
authorization, Kraken adapter, deployment. Next: real-data evaluation and the rest of M2.

## Architecture (see `docs/spec/architecture.md`)

Nine-stage pipeline (D-29): data -> regime -> eligible strategies -> candidate signals ->
ensemble -> deterministic risk approve/modify/reject -> deterministic sizing -> paper
execution -> journal. M1 implements every stage; regime and ensemble are pass-through.

Principles that constrain every change:

1. Paper by default; real-money spot trading only through the gated live environment
   (ADR-023). No leverage, margin, shorting, withdrawal, or transfer code paths (T-46).
2. Deterministic risk code has final authority. Strategies never size; every order comes from
   an approved `RiskDecision` and passes the execution gate.
3. Never invent risk values. `TBD` means fail closed (exit 3); experiment values only in
   backtests, always labelled.
4. `trader.domain` imports only the stdlib and Pydantic (D-44).
5. Decimal arithmetic and UTC-only time (ADR-017); determinism (identical runs give identical
   journal hashes).
6. Journal before act; append-only, hash-chained journal (ADR-018, ADR-019).

## Stack and conventions

- Python 3.11+, `uv` (environment and lock), Pydantic v2, Typer, PyYAML, jsonschema, pandas,
  numpy, pyarrow, SQLite.
- `ruff` (lint; `ruff format` is black-compatible), `mypy` (strict for `trader.domain.*` and
  `trader.risk.*`), `pytest` + `hypothesis` + `pytest-cov`.
- Google-style docstrings, type hints, files under 500 lines, `# Reason:` comments for
  non-obvious logic, and tests under `tests/` (unit, integration, e2e, safety).
- Decision IDs (D/H/R/UD/RR/EG/...) are referenced in code comments.
