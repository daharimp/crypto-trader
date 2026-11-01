# ai-crypto-trader

AI-assisted crypto **paper-trading** research system: milestone **M1**, the first vertical slice.

> **Safety boundary (ADR-023).** Paper/simulated by default. Real-money **spot** trading on
> Kraken exists only in the gated `live` environment: owner-signed authorization with a
> capital cap, a paper track record, an activation record, and a validate-only preflight.
> There is no leverage, margin, short selling, derivatives trading, withdrawal, or transfer
> code. Deterministic risk controls have final authority. Results are not forecasts, and
> profitability is not guaranteed or implied. You can lose real money.

## What M1 does

```text
Validated Balanced paper profile -> BTC and ETH candles -> data-quality checks
-> buy-and-hold benchmarks -> sma_trend baseline -> SignalCandidate events
-> deterministic RiskProfile checks (RR-01..RR-20) -> execution gate (EG-01..EG-05)
-> simulated fills -> append-only hash-chained journal -> report vs benchmarks
```

Risk values come only from **owner decisions** (UD-01 to UD-21). On 2026-11-01 the owner
approved them (record: `docs/spec/product-requirements.md` §10.2, ADR-022), except UD-14
(intraday sleeve, disabled) and UD-20 (venue). The code never fills in a missing value:

- The shipped Balanced profile backtests with **approved** values. Its concentration caps stay
  labelled **hypotheses** (H-01 to H-04), and every report lists them in a
  "Values used that are NOT owner-approved" banner.
- Any value still `TBD` makes a run **stop with exit code 3** and lists the UD IDs. Tests prove
  this against a frozen all-`TBD` copy of the configs in `tests/fixtures/configs/`.
- Experiment parameter sets may only target unresolved or hypothesis fields, and only in
  backtests. `EXP-2026-001` now targets approved fields, so it is rejected (exit 2).
- `paper` is refused until profile activation (BL-028) exists.

## Live trading on Kraken

Start here: **[`docs/operations/RUNBOOK.md`](docs/operations/RUNBOOK.md)**: server setup,
paper trading on live prices, the API key (no withdrawal permission), preflight,
authorization (UD-22), going live, daily operation, and emergencies.

```bash
trader profile activate PROFILE --environment paper|live --reason "..."   # BL-028
trader session run --profile PROFILE --environment paper|live              # BL-027
trader session status | flatten --reason ... | reset-breaker --reason ...
trader live preflight --profile PROFILE        # validate-only; places no orders
```

Deployment: `Dockerfile` and `docker-compose.yml` (services `paper`, `live` (opt-in profile),
and `cli`). Keys and alert settings go in `.env` on the server (`.env.example`).

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). No secrets and no network access
are needed.

```bash
uv sync                     # includes ccxt (Kraken data and the live adapter)
uv run ruff check .
uv run mypy src
uv run pytest               # 241 tests; add --cov=trader --cov-branch for coverage
uv run trader version
```

## Commands (handoff §10)

```bash
# Owner-approved configuration: exit 0
uv run trader profile validate configs/profiles/balanced-paper.yaml --environment backtest

# Paper is refused until profile activation exists (BL-028): exit 2
uv run trader profile validate configs/profiles/balanced-paper.yaml --environment paper

# Experiments cannot override approved values (RP-12): exit 2
uv run trader profile validate configs/profiles/balanced-paper.yaml --environment backtest \
  --experiment experiments/EXP-2026-001-vertical-slice.yaml

# Fail closed on unresolved values (frozen M1 baseline): exit 3 and lists the UD IDs
TRADER_CONFIGS_DIR=tests/fixtures/configs uv run trader profile validate \
  tests/fixtures/configs/profiles/balanced-paper.yaml --environment backtest

# Data (prints dataset IDs; datasets are immutable and content-addressed)
uv run trader data synth --instrument BTC-USD --timeframe 4h --start 2023-01-01T00:00:00Z \
  --end 2026-01-01T00:00:00Z --seed 42 --start-price 30000
uv run trader data synth --instrument ETH-USD --timeframe 4h --start 2023-01-01T00:00:00Z \
  --end 2026-01-01T00:00:00Z --seed 43 --start-price 2000
uv run trader data list
uv run trader data validate <DATASET_ID>
uv run trader data import --csv FILE --instrument BTC-USD --timeframe 4h --source-label NAME
uv run trader data fetch --exchange kraken --symbol BTC/USD --instrument BTC-USD \
  --timeframe 4h --start ... --end ...        # public OHLCV only

# Vertical slice (evaluation starts after 365 days of history for eligibility)
uv run trader backtest run --profile configs/profiles/balanced-paper.yaml \
  --datasets <BTC_DATASET_ID>,<ETH_DATASET_ID> --strategy sma_trend --timeframe 4h \
  --start 2024-01-01T00:00:00Z
uv run trader report show <RUN_ID> [--format md|json]
uv run trader journal verify <RUN_ID>

# Persisted kill switch (governs paper sessions; backtests record it)
uv run trader killswitch status
uv run trader killswitch engage --reason "drill"
uv run trader killswitch disengage --reason "drill complete"
```

One-command offline demo (about 30 s): `uv run python scripts/demo_vertical_slice.py`

**Exit codes:** 0 success · 1 internal error · 2 invalid input (schema, policy, data quality,
safety) · 3 blocked by unresolved decisions · 4 integrity verification failed.

Configuration is read from `configs/` (override with `TRADER_CONFIGS_DIR`). Runtime data lives in the git-ignored `data/` directory (override with `TRADER_DATA_DIR`):
`datasets/`, `journal/journal.sqlite`, `state/operational.sqlite`, `reports/<run_id>/`,
`experiments/`, `logs/<run_id>.jsonl`.

## Layout

| Path | Contents |
|---|---|
| `src/trader/domain/` | Framework-neutral Pydantic contracts (stdlib + pydantic only, T-47) |
| `src/trader/profiles/` | Loader, policy rules PV/RP, experiment overlay, blockers, compiler |
| `src/trader/data/` | CSV, synthetic, and optional CCXT providers; DQ-01..DQ-12; immutable store; snapshots |
| `src/trader/universe/` | Asset registry and point-in-time eligibility |
| `src/trader/features/`, `regimes/`, `strategies/`, `ensemble/` | features-m1, null regime, `sma_trend` 1.0.0, pass-through ensemble |
| `src/trader/risk/` | RR-01..RR-20, sizing, loss state, breaker, lockout, cooldowns, kill switch |
| `src/trader/execution/` | Gate EG-01..EG-05, adapter allowlist, simulator, Kraken live adapter |
| `src/trader/session/` | Forward paper/live sessions, Kraken data, state, flatten, alerts, preflight |
| `src/trader/portfolio/`, `journal/`, `evaluation/`, `pipeline/`, `backtest/`, `cli/` | Ledger, journal, benchmarks/metrics/report, decision cycle, runner, CLI |
| `configs/`, `schemas/`, `experiments/` | Shipped configuration (`TBD` values untouched) |
| `docs/spec/` | The full specification package (start with `code-session-handoff.md`) |
| `docs/decisions/` | ADR-001..ADR-018 (from the spec), ADR-019+ (implementation decisions) |
| `BLOCKERS.md` | Blocker log (open: UD-22 live cap and paper prerequisite) |
| `PLANNING.md`, `TASK.md` | Architecture summary and task tracking |

Regenerate schemas and profile configs from the spec with
`uv run python scripts/extract_spec_configs.py`.

## Specification

The controlling specification is in [`docs/spec/`](docs/spec/README.md). The decision
registers are `product-requirements.md` §3, and the unresolved decisions with options are
§10. M1 definition of done: `code-session-handoff.md` §11.
