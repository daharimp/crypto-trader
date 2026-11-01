# Code Session Handoff: AI-Assisted Crypto Paper-Trading System, First Vertical Slice (M1)

**Audience:** Microsoft Copilot Code (implementation session)
**Version:** 0.2
**Date:** 2026-10-08
**Owner:** Dahari Morgan-Parker
**Package:** This handoff belongs to a specification package (`README.md` lists all files). Copy the whole package into `docs/spec/` in the new repository. **This document is self-contained for M1:** everything needed to implement the first vertical slice is here. Other package files give background and later-phase detail.

---

## 0. Your role and instructions

You are implementing the first vertical slice (M1) of an AI-assisted crypto **paper-trading** research system in Python. Work through §8 in order. After each step, run the tests. Stop when the definition of done (§11) is met.

### 0.1 Non-negotiable rules

1. **Paper, dry-run, or simulated funds only.** Do **not** add real-money trading, live order placement, leverage, margin, short selling, futures/options/perpetual trading, withdrawals, or transfers, in any form: no functions, flags, adapters, configuration options, or "disabled for now" code paths. Do not call private or authenticated exchange APIs. Do not read or store API keys.
2. **Deterministic risk code has final authority.** Every order must come from an approved `RiskDecision` and pass the execution gate. Strategies never size orders. Nothing bypasses the risk engine.
3. **Never invent risk values.** Values marked `TBD` in configuration are unresolved owner decisions (IDs `UD-nn`). Do not replace them with defaults, constants, or "reasonable values" in code, configuration, or tests (tests use labelled fixtures, §9.1). A run that needs a `TBD` value must stop with exit code 3 and list the UD IDs.
4. **Stop and document blockers rather than bypassing missing risk requirements.** If you cannot proceed without a risk value, a safety-relevant interpretation, or a capability outside these rules, write an entry in `BLOCKERS.md` (template in §12), keep the system fail-closed, and continue with work that does not depend on it. Never weaken a test or a check to make progress.
5. **When in doubt, choose the more restrictive behavior** and record the choice in `BLOCKERS.md` or an ADR.
6. **Keep domain contracts framework-neutral.** `trader.domain` may import only the Python standard library and Pydantic.
7. **No guaranteed-profit language.** Reports and docs must never claim or imply guaranteed profitability.
8. **No UI in M1.** CLI and core engine only. Do not add a dashboard, web API, or LLM calls.

### 0.2 Status labels you will see

| Label | Meaning | What you do |
|---|---|---|
| APPROVED (`D-nn`) | Owner decision | Implement exactly |
| HYPOTHESIS (`H-nn`) | Labelled starting value (Balanced concentration caps) | Use it, label it `hypothesis` in outputs |
| RECOMMENDATION (`R-nn`, `RT-nn`) | Proposed design, not owner-approved | Implement as specified here (it is the M1 design); note in code comments where relevant |
| UNRESOLVED (`UD-nn`) | Open owner decision, value `TBD` | Never fill in. Fail closed |

---

## 1. Context in brief

- **Project:** research and engineering system (D-01) whose objective is to "balance strong returns with consistent performance and controlled drawdown" (D-05). It must not claim or assume guaranteed profitability (D-07).
- **Capital:** simulated $2,500 (D-04).
- **Risk model:** the owner selects Conservative, Balanced, or Aggressive (initially Balanced, D-09). The system adapts only inside the selected profile's boundaries (D-10). Loss handling: (1) reassess signals and conditions; (2) reduce size as losses accumulate; (3) hard thresholds override every strategy and model; (4) stop opening new trades at the profile's circuit breaker (D-12). AI and ML may recommend but not bypass hard limits (D-14).
- **Pace:** adaptive holding; V1 decision timeframes 1h and 4h (D-15, D-16). High-frequency and latency-arbitrage trading are out of scope (D-21).
- **Universe:** rules-based tiers Core, Major, Speculative, Blocked. Core = BTC and ETH. Every asset must pass eligibility checks (D-25, D-26). Balanced concentration hypotheses: Core 35% per asset (H-01), Major 15% (H-02), Speculative 5% (H-03), Speculative total 10% (H-04).
- **Strategy architecture:** a regime-aware ensemble in nine stages: data → regime → eligible strategies → candidate signals → ensemble → deterministic risk approve/modify/reject → deterministic sizing → paper execution → journal (D-29). M1 implements every stage, some as pass-through.
- **Execution:** in paper mode, approved orders execute automatically with no approval click (D-33, D-34). The owner has a manual kill switch (D-35). Every order is traceable to its signal, strategy/model versions, risk decision, configuration, and market-data timestamp (D-36).

### 1.1 The M1 slice (D-46)

```text
Validated Balanced paper profile
  -> load BTC and ETH historical candles
  -> validate data quality
  -> run buy-and-hold benchmark
  -> run one trend/momentum baseline (sma_trend)
  -> generate SignalCandidate events
  -> apply deterministic RiskProfile checks
  -> simulate orders using paper/dry-run execution
  -> persist TradeEvent journal
  -> report returns, fees, drawdown, and benchmark comparison
```

**The slice is not complete unless tests prove that invalid profiles, unsupported assets, stale data, excessive sizing, duplicate orders, breached loss limits, and disabled execution states are rejected (D-47).**

### 1.2 How the slice runs although risk values are unresolved

Most Balanced risk values are `TBD`. The slice handles this with **experiment parameter sets** (ADR-016):

- Running a backtest with only the shipped profile **must fail** with exit code 3 and list the unresolved UD IDs (this proves fail-closed behavior).
- Running it with `--experiment experiments/EXP-2026-001-vertical-slice.yaml` supplies labelled, non-approved values for research backtests only. Every report shows them in a provenance banner. The `paper` environment refuses experiment values.

---

## 2. Scope

**In scope for M1:** backlog items BL-001 to BL-020 (§8): repository, contracts, profile compiler, configuration, data providers and quality checks, datasets, eligibility, features, benchmarks, `sma_trend`, pass-through regime and ensemble stages, risk engine, execution gate, simulator, portfolio, journal, backtest runner, reports, kill switch, tests.

**Out of scope for M1:** forward (wall-clock) paper sessions, profile activation commands, other strategies, regime classifier logic, multi-strategy ensembles, walk-forward harness, explanations, ML, Freqtrade, Docker, API, dashboard, conversation, hosting, alerts beyond logs. Do not start these.

---

## 3. Repository structure

```text
ai-crypto-trader/
├── README.md                      # setup, commands (§10), safety statement
├── BLOCKERS.md                    # §12 template; empty list if none
├── pyproject.toml
├── uv.lock
├── .gitignore                     # includes data/, .env, *.sqlite, .venv/
├── .env.example                   # comment only: "No secrets are required for M1."
├── configs/
│   ├── profiles/balanced-paper.yaml
│   ├── risk/{conservative,balanced,aggressive}.yaml
│   ├── universe/{assets,eligibility}.yaml
│   ├── strategies/sma_trend.yaml
│   ├── costs/{low,base,stress}.yaml
│   └── environments/{backtest,paper}.yaml
├── experiments/EXP-2026-001-vertical-slice.yaml
├── schemas/{trading-profile,risk-profile}.schema.yaml   # Document 1 of each spec file
├── docs/
│   ├── spec/                      # the full specification package
│   ├── decisions/                 # ADR-000-template.md, ADR-001 ... ADR-018 stubs
│   ├── experiments/
│   └── operations/
├── scripts/
│   ├── extract_spec_configs.py    # §6.1
│   └── demo_vertical_slice.py     # §10.2
├── src/trader/
│   ├── __init__.py                # __version__
│   ├── domain/                    # stdlib + pydantic only
│   │   ├── common.py  enums.py  candles.py  profiles.py  risk_profile.py
│   │   ├── market.py  features.py  regime.py  signals.py  ensemble.py
│   │   ├── risk.py  orders.py  execution.py  positions.py  events.py
│   │   └── experiments.py  compiled.py  universe.py  killswitch.py
│   ├── common/                    # clock.py ids.py canonical.py hashing.py logging.py decimal_utils.py revision.py
│   ├── profiles/                  # loader.py validator.py compiler.py blockers.py
│   ├── universe/                  # registry.py eligibility.py
│   ├── data/
│   │   ├── providers/             # base.py csv_provider.py synthetic.py ccxt_public.py
│   │   ├── quality.py  store.py  snapshots.py
│   ├── features/                  # definitions.py pipeline.py
│   ├── regimes/                   # null_classifier.py
│   ├── strategies/                # base.py sma_trend.py registry.py
│   ├── ensemble/                  # passthrough.py
│   ├── risk/                      # engine.py rules.py sizing.py loss_state.py controls.py intents.py
│   ├── portfolio/                 # ledger.py
│   ├── execution/                 # gate.py service.py adapters/{base.py,simulated.py,registry.py}
│   ├── journal/                   # store.py verify.py
│   ├── evaluation/                # benchmarks.py metrics.py report.py
│   ├── research/                  # experiments.py (definition loader, record writer)
│   ├── pipeline/                  # cycle.py (one decision cycle)
│   ├── backtest/                  # runner.py
│   └── cli/                       # main.py profile.py data.py backtest.py report.py journal.py killswitch.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/                  # profiles/, risk/, experiments/EXP-0000-*.yaml, candles/
│   ├── unit/  integration/  e2e/  safety/
└── data/                          # git-ignored: raw/ datasets/ journal/ state/ reports/ experiments/ logs/
```

---

## 4. Python stack

| Purpose | Choice |
|---|---|
| Language | Python 3.11+ |
| Environment and lock | `uv` |
| Contracts and validation | Pydantic v2 |
| CLI | Typer |
| Configuration | PyYAML (`safe_load`, `safe_load_all`) |
| Schema check of shipped configs | `jsonschema` (draft 2020-12) |
| Data | pandas, numpy, pyarrow (Parquet) |
| Storage | SQLite (stdlib `sqlite3`) and Parquet |
| Tests | pytest, pytest-cov, hypothesis |
| Lint and types | ruff, mypy |
| Optional extra | `ccxt` for public OHLCV only (extra `ccxt`; never required by tests) |

`pyproject.toml` essentials:

```toml
[project]
name = "ai-crypto-trader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pydantic>=2.7,<3", "typer>=0.12", "pyyaml>=6.0", "jsonschema>=4.21",
  "pandas>=2.2", "numpy>=1.26", "pyarrow>=15",
]
[project.optional-dependencies]
ccxt = ["ccxt>=4.3"]
[project.scripts]
trader = "trader.cli.main:app"
[dependency-groups]
dev = ["pytest>=8", "pytest-cov>=5", "hypothesis>=6.100", "ruff>=0.5", "mypy>=1.10",
       "pandas-stubs", "types-PyYAML"]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
packages = ["src/trader"]
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
[tool.ruff]
line-length = 100
[tool.mypy]
python_version = "3.11"
strict = false
[[tool.mypy.overrides]]
module = ["trader.domain.*", "trader.risk.*"]
strict = true
```

---

## 5. End-to-end behavior

### 5.1 Time convention (R-07)

- All datetimes are timezone-aware UTC. Reject naive datetimes everywhere (`NAIVE_TIMESTAMP`).
- Candles are labelled by `open_time_utc`; `close_time_utc = open_time_utc + timeframe`. A candle is usable only at or after its close time.
- Bars align to UTC: `1h` on the hour; `4h` at 00, 04, 08, 12, 16, 20.
- A decision cycle runs at each bar close `t` of the decision timeframe. It may use only candles with `close_time_utc <= t`.
- Orders decided at `t` fill at the **open of the next bar** (the bar whose `open_time_utc == t`). If that bar is missing, the order expires (`INTENT_EXPIRED`).
- **Fresh** at `t` means the candle with `close_time_utc == t` exists. Otherwise the snapshot is **stale**.
- The trading day is the UTC calendar day; day-start equity is equity marked at 00:00 UTC.

### 5.2 Backtest bar loop (per bar of the decision timeframe, instruments in sorted order)

```text
for each bar B (open_time = t0, close_time = t1) in the evaluation window, chronologically:
  1. FILLS AT OPEN (time t0): fill pending market orders decided at t0 (exits first, then entries)
     - on exit fill: cancel the instrument's resting protective stop
     - on entry fill: risk.build_protective_stop_intent(...) -> journal -> register with adapter
     - reconcile ledger vs adapter; mismatch -> engage run kill switch (RECONCILIATION_FAILED)
  2. INTRABAR STOPS: for positions with a resting stop, if B.low <= stop_price -> stop fill
     (price = min(stop_price, B.open) - slippage, clamped to [B.low, B.high]); STOP_TRIGGERED
  3. MARK TO MARKET at t1 (close prices); update high-water mark, drawdown, day-start equity at 00:00 UTC
  4. DECISION CYCLE at t1 (pipeline/cycle.py), per instrument:
     snapshot -> universe -> features -> regime (null) -> signals -> ensemble (pass-through)
     -> risk decision (RR-01..RR-20) -> order intent (journal first) -> execution gate -> adapter (pending)
  5. Journal CYCLE_COMPLETED
After the loop: compute benchmarks and metrics, write the report and the experiment run record, journal RUN_COMPLETED.
```

Warm-up: candles before `--start` are used for features and eligibility history only; no decisions before `--start`.

### 5.3 Kill switch scopes

- **Persisted kill switch** (`data/state/operational.sqlite`): controlled by `trader killswitch ...`. It governs paper sessions (V1). In M1, `backtest run` reads it and records its state in `RUN_STARTED` but does not obey it, because backtests are research on historical data (`architecture.md` §8.5).
- **Run-scoped kill switch:** an in-memory control inside each backtest, engaged by auto-triggers (reconciliation mismatch, repeated execution errors, journal write failure) or by tests through the API. RR-03 and EG-02 read it.

---

## 6. Configuration files to create

### 6.1 Extraction from the specification

`docs/spec/trading-profile.schema.yaml` and `docs/spec/risk-profile.schema.yaml` are multi-document YAML files. Write `scripts/extract_spec_configs.py` to split them:

| Source document | Destination |
|---|---|
| trading-profile Document 1 (JSON Schema) | `schemas/trading-profile.schema.yaml` |
| trading-profile Document 2 | `configs/profiles/balanced-paper.yaml` |
| risk-profile Document 1 (JSON Schema) | `schemas/risk-profile.schema.yaml` |
| risk-profile Documents 2, 3, 4 | `configs/risk/conservative.yaml`, `balanced.yaml`, `aggressive.yaml` |

If the spec files are unavailable, create the files from §6.2 and §6.3. Conservative and Aggressive are identical to Balanced except: `risk_profile_id`, `display_name`, `description`, `selection` (Conservative `initial_default: false, explicit_selection_required: false`; Aggressive `initial_default: false, explicit_selection_required: true`), and all four concentration values `{value: TBD, status: unresolved, ref: UD-13}`.

### 6.2 `configs/profiles/balanced-paper.yaml`

```yaml
schema_version: "1.0.0"
kind: TradingProfile
profile_id: balanced-paper
version: 1
status: validated
owner: Dahari Morgan-Parker
description: Initial Balanced paper-trading profile for the V1 vertical slice.
objective:
  objective_id: balance_returns_consistency_drawdown
  statement: "Balance strong returns with consistent performance and controlled drawdown."
  guaranteed_profitability_assumed: false
  decision_ref: "D-05"
capital: {paper_capital_usd: 2500, accounting_currency: USD, funds: simulated}
risk_selection:
  risk_profile_id: balanced
  risk_profile_version: 1
  adaptation: within_selected_profile_bounds
  profile_switching: owner_only
universe:
  construction: rules_based
  quote_currency: USD
  allowed_tiers: [core, major, speculative]
  core_assets: [BTC, ETH]
  manual_allowlist: []
  disallowed_assets: []
  instruments_in_scope: [BTC-USD, ETH-USD]
  eligibility_required_for_all: true
horizon:
  holding_period: adaptive
  primary_decision_timeframes: ["1h", "4h"]
  typical_holding: {description: "From roughly one hour through several days", enforced_limit: false}
  minute_data:
    permitted_roles: [entry_exit_refinement, approved_intraday_strategies]
    entry_exit_refinement_enabled: false
    intraday_strategies_enabled: false
  excluded_styles: [high_frequency, latency_arbitrage]
execution:
  permitted_environments: [backtest, paper]
  autonomy_mode: paper_autonomous
  per_trade_approval_required: false
  instrument_types: [spot]
  real_money_enabled: false
  leverage_allowed: false
  margin_allowed: false
  short_selling_allowed: false
  withdrawals_allowed: false
  transfers_allowed: false
explanations: {preference: every_decision, narrative_source: recorded_facts_only, ai_generated_narratives_enabled: false}
data_sources:
  active:
    - {source_id: market_candles, tier: "V1", required_for_trading: true}
```

### 6.3 `configs/risk/balanced.yaml`

```yaml
schema_version: "1.0.0"
kind: RiskProfile
risk_profile_id: balanced
version: 1
display_name: Balanced
description: >-
  Initial profile (D-09) for the objective in D-05. Concentration values are testable starting
  hypotheses (H-01 to H-04), not permanent production limits (D-28). All other numeric values
  are unresolved.
selection: {initial_default: true, explicit_selection_required: false}
global_hard_constraints:
  funds: simulated
  instrument_types: [spot]
  leverage_allowed: false
  margin_allowed: false
  short_selling_allowed: false
  withdrawals_allowed: false
  deterministic_final_authority: true
  ai_may_override_limits: false
  profile_switching: owner_only
loss_response:
  reassess_signals_and_conditions_each_cycle: true
  size_reduction_schedule: {method: TBD, steps: TBD, status: unresolved, ref: UD-15}
  hard_thresholds_override_all: true
  circuit_breaker_stops_new_trades: true
limits:
  portfolio_drawdown_circuit_breaker_pct: {value: TBD, status: unresolved, ref: UD-01}
  daily_loss_limit_pct: {value: TBD, status: unresolved, ref: UD-02}
  daily_loss_window: utc_calendar_day
  circuit_breaker_reset: owner_command_with_reason
sizing:
  risk_per_trade_pct: {value: TBD, status: unresolved, ref: UD-03}
  hard_stop_policy: {method: TBD, status: unresolved, ref: UD-16}
  adaptation:
    downward: loss_response_schedule
    upward_enabled: false
    upward_multiplier_max: {value: TBD, status: unresolved, ref: UD-15}
  quantity_rounding: round_down_to_instrument_step
concentration:
  applies_to: aggregate_exposure_across_sleeves
  core_per_asset_cap_pct: {value: 35, status: hypothesis, ref: H-01}
  major_per_asset_cap_pct: {value: 15, status: hypothesis, ref: H-02}
  speculative_per_asset_cap_pct: {value: 5, status: hypothesis, ref: H-03}
  speculative_total_cap_pct: {value: 10, status: hypothesis, ref: H-04}
allocation:
  total_exposure_cap_pct: {value: TBD, status: unresolved, ref: UD-12}
  minimum_reserve_pct_range: {low: TBD, high: TBD, status: unresolved, ref: UD-04}
  max_open_positions: {value: TBD, status: unresolved, ref: UD-12}
  intraday_allocation_cap_pct: {value: TBD, status: unresolved, ref: UD-14, candidates_under_test: [5, 10, 15, 20]}
  intraday_sleeve_limits:
    isolation: separate_ledger_no_borrowing_from_core
    daily_loss_limit_pct: {value: TBD, status: unresolved, ref: UD-14}
    drawdown_circuit_breaker_pct: {value: TBD, status: unresolved, ref: UD-14}
cooldown:
  after_consecutive_losing_trades:
    scope: strategy_instrument
    count: {value: TBD, status: unresolved, ref: UD-17}
    duration_hours: {value: TBD, status: unresolved, ref: UD-17}
data_and_execution_faults:
  stale_data:
    definition: missing_latest_expected_closed_candle
    action: block_new_orders_for_instrument
    paper_grace_seconds: {value: TBD, status: unresolved, ref: UD-17}
    escalate_to_kill_switch_after_stale_cycles: {value: TBD, status: unresolved, ref: UD-17}
  exchange_errors:
    retry_policy: idempotent_operations_only
    max_consecutive_errors_before_kill_switch: {value: TBD, status: unresolved, ref: UD-17}
  clock_skew_tolerance_seconds: {value: TBD, status: unresolved, ref: UD-17}
  reconciliation:
    internal_simulator: exact_match
    external_adapter_quantity_tolerance: {value: TBD, status: unresolved, ref: UD-17}
kill_switch:
  state_model: {values: [disengaged, engaged], source: operational_store, persisted_across_restarts: true, initial_state_on_first_start: disengaged}
  manual_engage: always_available
  manual_disengage: owner_command_with_reason
  automated_disengage_allowed: false
  ai_may_change_state: false
  effect_on_new_orders: block_all
  auto_engage_triggers: [reconciliation_mismatch, repeated_execution_errors, clock_skew_exceeded,
                         journal_write_failure, risk_config_invalid_mid_session, persistent_stale_data]
halt_and_liquidation:
  interim_behavior_until_resolved: hold_unchanged_including_attached_stops
  liquidation_policy_after_halt: {value: TBD, status: unresolved, ref: UD-19}
```

**Do not change any `TBD` above.** Only the owner may resolve them.

### 6.4 `configs/universe/assets.yaml` and `eligibility.yaml`

```yaml
# assets.yaml
schema_version: "1.0.0"
kind: AssetRegistry
version: 1
assets:
  - {asset_id: BTC, name: Bitcoin, tier: core, tier_status: approved, aliases: [XBT], blocked: false}
  - {asset_id: ETH, name: Ether, tier: core, tier_status: approved, aliases: [], blocked: false}
instruments:
  - {instrument_id: BTC-USD, base: BTC, quote: USD, type: spot, quantity_step: "0.00000001"}
  - {instrument_id: ETH-USD, base: ETH, quote: USD, type: spot, quantity_step: "0.00000001"}
market_symbol_map:
  - {market_id: "sim:BTC-USD", venue_id: sim, venue_symbol: BTC-USD, instrument_id: BTC-USD}
  - {market_id: "sim:ETH-USD", venue_id: sim, venue_symbol: ETH-USD, instrument_id: ETH-USD}
  - {market_id: "csv:BTC-USD", venue_id: csv, venue_symbol: BTC-USD, instrument_id: BTC-USD}
  - {market_id: "csv:ETH-USD", venue_id: csv, venue_symbol: ETH-USD, instrument_id: ETH-USD}
```

```yaml
# eligibility.yaml  (all thresholds UNRESOLVED, UD-18 / UD-06)
schema_version: "1.0.0"
kind: EligibilityRules
version: 1
criteria:
  liquidity:
    metric: median_daily_quote_volume_usd_30d
    min_by_tier:
      core: {value: TBD, status: unresolved, ref: UD-18}
      major: {value: TBD, status: unresolved, ref: UD-18}
      speculative: {value: TBD, status: unresolved, ref: UD-18}
  data_history:
    metric: days_of_continuous_history
    min_by_tier:
      core: {value: TBD, status: unresolved, ref: UD-18}
      major: {value: TBD, status: unresolved, ref: UD-18}
      speculative: {value: TBD, status: unresolved, ref: UD-18}
  spread:
    metric: median_relative_spread_bps
    max_by_tier:
      core: {value: TBD, status: unresolved, ref: UD-18}
      major: {value: TBD, status: unresolved, ref: UD-18}
      speculative: {value: TBD, status: unresolved, ref: UD-18}
    when_no_spread_data: {value: TBD, status: unresolved, ref: UD-18}
  support: {rule: instrument_has_market_mapping_for_active_venue}
  explicit_exclusion: {rule: not_in_profile_disallowed_assets_and_not_registry_blocked}
tier_assignment:
  core: owner_approved_only
  major: {value: TBD, status: unresolved, ref: UD-06}
  speculative: {value: TBD, status: unresolved, ref: UD-06}
```

### 6.5 Costs, strategy, environments

```yaml
# configs/costs/base.yaml   (low: fee 0.10, slippage 5; stress: fee 0.60, slippage 25; all RECOMMENDATION R-10)
schema_version: "1.0.0"
kind: CostScenario
scenario_id: base
fee_rate_pct: "0.40"          # per side, on fill notional
slippage_bps: "10"            # per side; includes half-spread in V1
execution_delay: next_bar_open
min_notional_usd: "10"
status: recommendation
ref: R-10
```

```yaml
# configs/strategies/sma_trend.yaml
schema_version: "1.0.0"
kind: StrategyRegistryEntry
strategy_id: sma_trend
version: 1.0.0
family: trend_momentum
kind_of_strategy: rule_based
sleeve: core
timeframes: ["1h", "4h"]
parameters: {fast: 20, slow: 50}        # RECOMMENDATION R-09
feature_set_version: features-m1-1.0.0
regime_eligibility: all                 # M1: null classifier
lifecycle_state: research
code_ref: trader.strategies.sma_trend:SmaTrend
```

```yaml
# configs/environments/backtest.yaml          # paper.yaml: environment paper, clock wall, kill_switch_scope persisted
schema_version: "1.0.0"
kind: EnvironmentConfig
environment: backtest
execution_enabled: true
adapter: simulated
clock: simulated
kill_switch_scope: run
```

### 6.6 `experiments/EXP-2026-001-vertical-slice.yaml`

Values come from the recommendations in `product-requirements.md` §10. They are **not approved**. They are accepted only in `backtest` and are labelled `experiment` everywhere.

```yaml
schema_version: "1.0.0"
kind: ExperimentDefinition
experiment_id: EXP-2026-001
title: Vertical-slice demonstration run
purpose: pipeline_verification
hypothesis: >-
  The validated Balanced paper profile, BTC and ETH candles, buy-and-hold benchmarks, and the
  sma_trend baseline run end to end through deterministic risk checks and simulated execution,
  producing a fully traceable journal and a reproducible report.
environment: backtest
trading_profile: configs/profiles/balanced-paper.yaml
strategy: {strategy_id: sma_trend, version: 1.0.0}
timeframe: 4h
cost_scenario: base
parameters:
  risk:
    limits.portfolio_drawdown_circuit_breaker_pct: {value: 15, source: "UD-01 option B (recommendation)"}
    limits.daily_loss_limit_pct: {value: 3, source: "UD-02 option A (recommendation)"}
    sizing.risk_per_trade_pct: {value: 1.0, source: "UD-03 option A (recommendation)"}
    sizing.hard_stop_policy:
      value: {method: atr_multiple, timeframe: decision_timeframe, atr_period_bars: 14, atr_multiple: 2.0}
      source: "UD-16 recommendation"
    loss_response.size_reduction_schedule:
      value:
        method: stepwise_fraction_of_breaker
        steps:
          - {drawdown_fraction_of_breaker_below: 0.3333, multiplier: 1.0}
          - {drawdown_fraction_of_breaker_below: 0.6667, multiplier: 0.5}
          - {drawdown_fraction_of_breaker_below: 1.0, multiplier: 0.25}
      source: "UD-15 option A (recommendation)"
    allocation.total_exposure_cap_pct: {value: 80, source: "UD-12 option A (recommendation)"}
    allocation.minimum_reserve_pct_range: {value: {low: 20, high: 40}, source: "UD-04 option A (recommendation)"}
    allocation.max_open_positions: {value: 5, source: "UD-12 option A (recommendation)"}
    cooldown.after_consecutive_losing_trades.count: {value: 3, source: "UD-17 recommendation"}
    cooldown.after_consecutive_losing_trades.duration_hours: {value: 24, source: "UD-17 recommendation"}
    data_and_execution_faults.exchange_errors.max_consecutive_errors_before_kill_switch: {value: 3, source: "UD-17 recommendation"}
  eligibility:
    liquidity.min_by_tier.core: {value: 50000000, source: "UD-18 option A (recommendation)"}
    data_history.min_by_tier.core: {value: 365, source: "UD-18 option A (recommendation)"}
    spread.when_no_spread_data: {value: not_applicable, source: "R-21 / UD-18 (recommendation)"}
```

---

## 7. Interfaces and module specifications

### 7.1 Domain conventions (`trader.domain.common`)

- Base model: `class DomainModel(BaseModel): model_config = ConfigDict(extra="forbid", frozen=True)`.
- `UtcDatetime`: annotated `datetime` that rejects naive values and normalizes to UTC.
- Money and quantities: `Decimal`, serialized as strings. Percentages `_pct` are 0 to 100.
- Every contract has `schema_version: Literal["1.0.0"]`.
- IDs: prefixed strings from an injectable `IdGenerator`. Backtests use run-scoped counters (`sig-000001`, `rsk-000001`, ...) so identical runs produce identical IDs (R-06).
- Canonical JSON (`trader.common.canonical`): UTF-8, `sort_keys=True`, `separators=(",", ":")`, Decimal as string, datetimes `YYYY-MM-DDTHH:MM:SSZ`. Hashes: `"sha256:" + hexdigest`.

### 7.2 Enumerations and codes (`trader.domain.enums`)

```text
Environment: backtest | paper
Side: buy | sell
Sleeve: core | intraday
OrderPurpose: entry | exit | protective_stop
OrderType: market | stop_market
EnsembleAction: enter_long | exit_long | hold | no_trade
NoTradeReason: SIGNAL_CONFLICT | REGIME_BLOCKED | DATA_STALE | DATA_UNCERTAIN | NO_ELIGIBLE_SIGNALS | BELOW_THRESHOLD
RiskStatus: approved | modified | rejected
RuleOutcome: pass | fail | clamped | not_evaluated | not_applicable
BindingConstraint: TIER_CAP | SPECULATIVE_CAP | TOTAL_EXPOSURE_CAP | RESERVE_FLOOR | AVAILABLE_CASH
ExecutionStatus: accepted | open | partially_filled | filled | canceled | rejected | expired | error
Provenance: approved | hypothesis | experiment | fixture
TrendState: trending_up | trending_down | range_bound | unknown
VolatilityState: low | normal | high | unknown
DataState: ok | uncertain | stale
RegimeMethod: not_evaluated | deterministic_rules | ml_model | ai_assisted

ReasonCode (risk and execution):
  PROFILE_NOT_RUNNABLE  RISK_CONFIG_UNRESOLVED  KILL_SWITCH_ENGAGED  EXECUTION_DISABLED
  SAFETY_VIOLATION  ASSET_NOT_SUPPORTED  ASSET_BLOCKED  ASSET_INELIGIBLE  STALE_DATA
  DATA_QUALITY_FAILED  DUPLICATE_ORDER  SPOT_CONSTRAINT_VIOLATION  CIRCUIT_BREAKER_OPEN
  DAILY_LOSS_LIMIT  COOLDOWN_ACTIVE  INTRADAY_SLEEVE_DISABLED  CONCENTRATION_LIMIT
  EXPOSURE_LIMIT  RESERVE_LIMIT  MAX_POSITIONS  SIZE_BELOW_MINIMUM  EXCESSIVE_SIZE
  RISK_DECISION_MISSING  RISK_DECISION_MISMATCH  ADAPTER_NOT_ALLOWED  INTENT_EXPIRED

ValidationErrorCode (compiler, CLI exit 2 unless noted):
  SCHEMA_INVALID  SAFETY_CONSTANT_VIOLATION  PROFILE_CONTRADICTION  RISK_PROFILE_CONTRADICTION
  AGGRESSIVE_NOT_ACKNOWLEDGED  RISK_PROFILE_NOT_FOUND  INTRADAY_NOT_APPROVED
  DATA_SOURCE_NOT_PERMITTED  PROFILE_NOT_RUNNABLE  PROFILE_VERSION_NOT_INCREMENTED
  EXPERIMENT_PARAMETERS_REJECTED  NAIVE_TIMESTAMP  DATA_QUALITY_FAILED  INSUFFICIENT_HISTORY
  RISK_CONFIG_UNRESOLVED (exit 3)  DATASET_INTEGRITY_FAILED (exit 4)  JOURNAL_INTEGRITY_FAILED (exit 4)

EventType:
  RUN_STARTED RUN_BLOCKED RUN_COMPLETED RUN_FAILED PROFILE_COMPILED DATASET_VALIDATED
  UNIVERSE_EVALUATED CYCLE_STARTED DATA_STALE PROVIDER_DEGRADED FEATURES_COMPUTED REGIME_ASSESSED
  SIGNAL_GENERATED ENSEMBLE_DECIDED RISK_EVALUATED ORDER_INTENT_CREATED ORDER_SUBMITTED
  ORDER_REJECTED ORDER_FILLED ORDER_CANCELED STOP_TRIGGERED POSITION_UPDATED
  CIRCUIT_BREAKER_OPENED DAILY_LOCKOUT_STARTED COOLDOWN_STARTED KILL_SWITCH_ENGAGED
  KILL_SWITCH_DISENGAGED EXECUTION_ERROR RECONCILIATION_FAILED EXPLANATION_GENERATED CYCLE_COMPLETED
```

### 7.3 Domain contracts (fields)

`TradingProfile` and `RiskProfile` mirror §6.2 and §6.3 exactly (nested Pydantic models; constants as `Literal`). Risk parameters are typed `PctParam`, `PctRangeParam`, `CountParam`, `HoursParam`, `SecondsParam`, `MultiplierParam`, `GenericParam`, `ChoiceParam`, `StopPolicy`, and `LossScalingSchedule`, each with `value` (or method/steps or low/high) that may be the literal string `"TBD"`, plus `status`, `ref`, and optional `approved_by`, `approved_on`, `note`, `candidates_under_test`. Validators: `status == unresolved` if and only if the value is `TBD`; `approved` requires `approved_by` and `approved_on`; `hypothesis` refs match `H-nn`; `unresolved` refs match `UD-nn`.

```python
class Candle(DomainModel):
    open_time_utc: UtcDatetime; close_time_utc: UtcDatetime
    open: Decimal; high: Decimal; low: Decimal; close: Decimal; volume: Decimal
    # validators: prices > 0, low <= min(open, close), high >= max(open, close), volume >= 0

class SourceRef(DomainModel):
    provider_id: str; venue_id: str; retrieved_at_utc: UtcDatetime | None

class MarketSnapshot(DomainModel):
    schema_version: Literal["1.0.0"]; snapshot_id: str; cycle_id: str
    instrument_id: str; timeframe: str; as_of_utc: UtcDatetime
    latest_bar: Candle | None; expected_latest_close_utc: UtcDatetime; is_fresh: bool
    quality_status: Literal["ok", "failed"]; dataset_ids: list[str]; source: SourceRef
    # validators: latest_bar.close_time_utc <= as_of_utc;
    #   is_fresh == (latest_bar is not None and latest_bar.close_time_utc == expected_latest_close_utc)

class FeatureSet(DomainModel):
    schema_version: Literal["1.0.0"]; feature_set_id: str; instrument_id: str; timeframe: str
    as_of_utc: UtcDatetime; feature_set_version: str; definitions_hash: str
    values: dict[str, Decimal | None]; max_input_close_time_utc: UtcDatetime
    warmup_complete: bool; input_dataset_ids: list[str]
    # validator: max_input_close_time_utc <= as_of_utc

class RegimeAssessment(DomainModel):
    schema_version: Literal["1.0.0"]; regime_assessment_id: str; instrument_id: str; timeframe: str
    as_of_utc: UtcDatetime; trend_state: TrendState; volatility_state: VolatilityState
    data_state: DataState; label: str; confidence: Decimal | None; method: RegimeMethod
    classifier_id: str; classifier_version: str; model_version: str | None; feature_set_id: str | None

class Invalidation(DomainModel):
    kind: str; level: Decimal | None; reason: str

class SignalCandidate(DomainModel):
    schema_version: Literal["1.0.0"]; signal_id: str; correlation_id: str; cycle_id: str
    instrument_id: str; timeframe: str; decision_time_utc: UtcDatetime
    strategy_id: str; strategy_version: str; sleeve: Sleeve; side: Side
    strength: Decimal                   # 0..1
    confidence: Decimal | None          # 0..1
    expected_horizon: str | None; entry_reference_price: Decimal; invalidation: Invalidation
    feature_set_id: str; regime_assessment_id: str
    model_id: str | None; model_version: str | None; rationale_codes: list[str]
    # NO quantity / notional / leverage / stop fields (extra="forbid")

class IgnoredSignal(DomainModel):
    signal_id: str; reason: str
class Conflict(DomainModel):
    detected: bool; buy_votes: int; sell_votes: int

class EnsembleDecision(DomainModel):
    schema_version: Literal["1.0.0"]; ensemble_decision_id: str; correlation_id: str; cycle_id: str
    instrument_id: str; decision_time_utc: UtcDatetime; action: EnsembleAction
    position_state: Literal["flat", "long"]; contributing_signal_ids: list[str]
    ignored_signals: list[IgnoredSignal]; combined_score: Decimal | None; confidence: Decimal | None
    conflict: Conflict; no_trade_reason: NoTradeReason | None
    ensemble_id: str; ensemble_version: str; weighting_method: str; regime_assessment_id: str
    # validators: no_trade => no_trade_reason set; enter_long => position_state == "flat";
    #             exit_long => position_state == "long"

class RuleResult(DomainModel):
    rule_id: str; rule_version: str; outcome: RuleOutcome; reason_code: ReasonCode | None
    detail: dict[str, str]              # inputs and threshold references, as strings

class LossState(DomainModel):
    equity_usd: Decimal; hwm_equity_usd: Decimal; drawdown_pct: Decimal
    day_start_equity_usd: Decimal; daily_pnl_pct: Decimal; loss_scaling_multiplier: Decimal
    breaker_open: bool; daily_lockout_active: bool

class StopSpec(DomainModel):
    method: str; stop_distance_pct: Decimal; atr_value: Decimal | None

class RiskDecision(DomainModel):
    schema_version: Literal["1.0.0"]; risk_decision_id: str; correlation_id: str; cycle_id: str
    ensemble_decision_id: str; instrument_id: str; decision_time_utc: UtcDatetime
    action_evaluated: Literal["enter_long", "exit_long"]; status: RiskStatus
    approved_quantity: Decimal; approved_notional_usd: Decimal; reference_price: Decimal
    stop: StopSpec | None; loss_state: LossState; rule_results: list[RuleResult]
    reason_codes: list[ReasonCode]; binding_constraint: BindingConstraint | None
    config_hash: str; risk_engine_version: str
    # validators: rejected => quantity == 0 and reason_codes non-empty;
    #             approved/modified => quantity > 0; modified => binding_constraint set

class VersionRef(DomainModel):
    id: str; version: str

class OrderIntent(DomainModel):
    schema_version: Literal["1.0.0"]; order_intent_id: str; correlation_id: str; cycle_id: str
    idempotency_key: str; risk_decision_id: str; ensemble_decision_id: str
    signal_ids: list[str]; strategy_versions: list[VersionRef]; model_versions: list[VersionRef]
    instrument_id: str; side: Side; purpose: OrderPurpose; order_type: OrderType
    quantity: Decimal; reference_price: Decimal; stop_price: Decimal | None
    attached_stop_distance_pct: Decimal | None      # entries only
    parent_order_intent_id: str | None             # protective stops only
    notional_estimate_usd: Decimal; valid_until_utc: UtcDatetime
    environment: Environment; funds: Literal["simulated"]; config_hash: str
    market_data_timestamp_utc: UtcDatetime         # close time of the latest candle used
    decision_time_utc: UtcDatetime; created_at_utc: UtcDatetime
    # validators: entry => side buy and order_type market;
    #   exit => side sell and market; protective_stop => side sell, stop_market, stop_price set;
    #   signal_ids non-empty; strategy_versions non-empty; quantity > 0
    # idempotency_key = sha256(canonical([config_hash, instrument_id, side, purpose, decision_time_utc]))

class ExecutionReport(DomainModel):
    schema_version: Literal["1.0.0"]; execution_report_id: str; order_intent_id: str
    correlation_id: str; adapter_id: str; adapter_version: str; venue: str
    status: ExecutionStatus; reason_code: ReasonCode | None
    filled_quantity: Decimal; average_fill_price: Decimal | None; expected_price: Decimal
    fees_usd: Decimal; fee_rate_pct: Decimal; slippage_bps_assumed: Decimal; slippage_usd: Decimal
    submitted_at_utc: UtcDatetime; filled_at_utc: UtcDatetime | None
    fill_bar_open_time_utc: UtcDatetime | None; latency_ms: int

class PositionLine(DomainModel):
    instrument_id: str; tier: str; sleeve: Sleeve; quantity: Decimal; avg_entry_price: Decimal
    mark_price: Decimal; market_value_usd: Decimal; unrealized_pnl_usd: Decimal
    realized_pnl_usd: Decimal; stop_price: Decimal | None; opened_at_utc: UtcDatetime
    owner_strategy_ids: list[str]

class PositionSnapshot(DomainModel):
    schema_version: Literal["1.0.0"]; position_snapshot_id: str; as_of_utc: UtcDatetime
    cash_usd: Decimal; committed_cash_usd: Decimal; equity_usd: Decimal; hwm_equity_usd: Decimal
    drawdown_pct: Decimal; day_start_equity_usd: Decimal; daily_pnl_pct: Decimal
    positions: list[PositionLine]; exposure_by_instrument_pct: dict[str, Decimal]
    exposure_by_tier_pct: dict[str, Decimal]; total_exposure_pct: Decimal
    open_positions_count: int; breaker_open: bool; daily_lockout_until_utc: UtcDatetime | None
    cooldowns: dict[str, UtcDatetime]   # key "strategy_id|instrument_id" -> until
    # validators: equity == cash + sum(market_value); quantities >= 0; cash >= 0

class TradeEvent(DomainModel):
    schema_version: Literal["1.0.0"]; event_id: str; run_id: str; seq: int
    event_type: EventType; event_time_utc: UtcDatetime; recorded_at_utc: UtcDatetime
    cycle_id: str | None; correlation_id: str | None
    payload_type: str; payload_schema_version: str; payload: dict[str, Any]
    prev_event_hash: str; event_hash: str; code_revision: str; config_hash: str

class ExperimentRecord(DomainModel):
    schema_version: Literal["1.0.0"]; experiment_id: str      # ^EXP-\d{4}-\d{3}$
    title: str; hypothesis: str; purpose: str; status: str
    data: dict[str, Any]; strategy: VersionRef; profile_refs: dict[str, str]
    experiment_parameters: list[dict[str, str]]   # field, value, source, provenance
    assumptions: dict[str, str]; method: dict[str, Any]; results: dict[str, Any]
    overfit_checks: dict[str, str]; failure_analysis: str | None
    decision: dict[str, str] | None; reproduction: dict[str, str]; run_ids: list[str]
```

Supporting types: `CompiledProfile` (`trader.domain.compiled`), `DatasetManifest`, `UniverseSnapshot` and `AssetEligibility` (`trader.domain.universe`), `KillSwitchState` (`trader.domain.killswitch`), `ExperimentDefinition` (`trader.domain.experiments`).

```python
class EffectiveValue(DomainModel):
    field: str; value: Any; provenance: Provenance; ref: str; source: str | None

class Blocker(DomainModel):
    field: str; ref: str; reason: str

class CompiledProfile(DomainModel):
    schema_version: Literal["1.0.0"]; environment: Environment
    trading_profile: VersionRef; trading_profile_hash: str
    risk_profile: VersionRef; risk_profile_hash: str
    eligibility_rules_hash: str; asset_registry_hash: str
    experiment_id: str | None; experiment_hash: str | None
    cost_scenario: dict[str, str]; effective: dict[str, EffectiveValue]
    blockers: list[Blocker]; errors: list[str]; runnable: bool
    compiler_version: str; config_hash: str   # sha256 of canonical JSON of all fields except config_hash
```

### 7.4 Profile compiler (`trader.profiles.compiler`)

```python
def compile_profile(profile_path: Path, environment: Environment,
                    experiment_path: Path | None = None,
                    configs_root: Path = Path("configs")) -> CompiledProfile: ...
```

Algorithm:

1. Load YAML and validate the TradingProfile against Pydantic (and, in tests, the JSON Schema). Failures → `SCHEMA_INVALID` or `SAFETY_CONSTANT_VIOLATION` (exit 2).
2. Run PV-01 to PV-10:
   - PV-01: disallowed assets must not overlap Core or allowlist (`PROFILE_CONTRADICTION`).
   - PV-02: in-scope instruments must have a base asset in Core or the allowlist and quote `USD`.
   - PV-03: Aggressive needs an acknowledgement (`AGGRESSIVE_NOT_ACKNOWLEDGED`).
   - PV-04: `configs/risk/<id>.yaml` exists with a matching version (`RISK_PROFILE_NOT_FOUND`).
   - PV-05: intraday enabled needs an approved intraday cap (`INTRADAY_NOT_APPROVED`).
   - PV-06: refinement enabled needs that role and a 1m source.
   - PV-07: V1 sources required for trading must be tier V1 (`DATA_SOURCE_NOT_PERMITTED`).
   - PV-08: `draft` and `suspended` cannot run; `backtest` needs `validated` or `active`; `paper` needs `active` plus an activation record (always missing in M1) (`PROFILE_NOT_RUNNABLE`).
   - PV-09: if Core assets exist, `allowed_tiers` must include `core`.
   - PV-10: if `(profile_id, version)` was compiled before with a different content hash (recorded in `data/state/operational.sqlite`), fail with `PROFILE_VERSION_NOT_INCREMENTED`.
3. Load the selected RiskProfile, eligibility rules, asset registry, and cost scenario.
4. If an experiment is given: reject in `paper` (`EXPERIMENT_PARAMETERS_REJECTED`). In `backtest`, each parameter path must point to a field whose current status is `unresolved` or `hypothesis` and must not be under `global_hard_constraints`, `kill_switch`, `halt_and_liquidation`, or the `loss_response` constants. Apply values with provenance `experiment`. Files under `tests/fixtures/` with IDs starting `EXP-0000-` get provenance `fixture`.
5. Build `effective` for every leaf value with provenance (`approved`, `hypothesis`, `experiment`, `fixture`).
6. Required fields for the environment (§7.4.1). Any still `TBD` → `Blocker(field, ref=UD-nn)`.
7. Run RP-01 to RP-07 on resolved values (`RISK_PROFILE_CONTRADICTION`).
8. `runnable = not errors and not blockers`. Compute `config_hash`.
9. CLI exit code: 2 if `errors`, else 3 if `blockers`, else 0. Print all errors and blockers either way.

#### 7.4.1 Required fields

- **backtest:** `limits.portfolio_drawdown_circuit_breaker_pct`, `limits.daily_loss_limit_pct`, `loss_response.size_reduction_schedule`, `sizing.risk_per_trade_pct`, `sizing.hard_stop_policy`, `concentration.<tier>_per_asset_cap_pct` for each tier present among in-scope instruments (Core in M1), `concentration.speculative_total_cap_pct` if any Speculative asset, `allocation.total_exposure_cap_pct`, `allocation.minimum_reserve_pct_range`, `allocation.max_open_positions`, `cooldown.after_consecutive_losing_trades.count`, `cooldown.after_consecutive_losing_trades.duration_hours`, `data_and_execution_faults.exchange_errors.max_consecutive_errors_before_kill_switch`, and eligibility `liquidity.min_by_tier.<tier>`, `data_history.min_by_tier.<tier>`, plus `spread.when_no_spread_data` (no spread provider in M1).
- **paper (additional):** `data_and_execution_faults.stale_data.paper_grace_seconds`, `...escalate_to_kill_switch_after_stale_cycles`, `data_and_execution_faults.clock_skew_tolerance_seconds`, `halt_and_liquidation.liquidation_policy_after_halt`. Paper accepts only `approved` or `hypothesis` provenance.

Expected result for the shipped Balanced profile in `backtest` without an experiment: exit 3 with blockers for UD-01, UD-02, UD-03, UD-04, UD-12, UD-15, UD-16, UD-17, and UD-18.

### 7.5 Data (`trader.data`)

```python
class CandleProvider(Protocol):
    provider_id: str
    def fetch_candles(self, instrument_id: str, timeframe: str,
                      start_utc: datetime, end_utc: datetime) -> list[Candle]: ...

class DatasetStore:
    def create(self, candles: list[Candle], instrument_id: str, timeframe: str,
               source: SourceRef, source_label: str) -> DatasetManifest: ...   # idempotent
    def load(self, dataset_id: str) -> tuple[DatasetManifest, pd.DataFrame]: ...  # re-verifies hash
    def list(self) -> list[DatasetManifest]: ...

def run_quality_checks(df: pd.DataFrame, timeframe: str, retrieved_at_utc: datetime | None) -> QualityReport: ...
class SnapshotBuilder:
    def snapshot(self, instrument_id: str, timeframe: str, t: datetime) -> MarketSnapshot: ...
    def window(self, instrument_id: str, timeframe: str, t: datetime, bars: int) -> pd.DataFrame: ...
    # returns only rows with close_time_utc <= t
```

- **Synthetic provider** (deterministic, `numpy.random.Generator(PCG64(seed))`): three-state Markov regime (up, down, flat; stay probability 0.98 per bar). Per-bar log return ~ Normal(mu, sigma) with fixture constants per 4h bar: up (0.0015, 0.012), down (−0.0015, 0.015), flat (0.0, 0.008); scale both by √(bar_hours / 4) for other timeframes. `open` = previous close; `close = open × exp(r)`; `high = max(open, close) × exp(|N(0, sigma/2)|)`; `low = min(open, close) × exp(−|N(0, sigma/2)|)`; volume per bar = `daily_quote_volume_usd / bars_per_day / close × lognormal(0, 0.3)` with default `daily_quote_volume_usd = 1e9`. Quantize prices to 0.01 and volume to 0.000001 using `Decimal(str(round(x, n)))`. These are test-fixture constants with no market meaning.
- **CSV provider:** columns `open_time_utc,open,high,low,close,volume`; ISO-8601 with `Z`, or integer epoch milliseconds.
- **CCXT public provider** (optional extra): `ccxt.<exchange>().fetch_ohlcv(symbol, timeframe, since, limit)` only; the exchange is a required CLI argument; no keys; never imported unless used; tests mock it.
- **Quality checks:** DQ-01 schema, DQ-02 UTC, DQ-03 alignment, DQ-04 ordering, DQ-05 duplicates, DQ-06 gaps, DQ-07 OHLC consistency, DQ-08 volume, DQ-09 outlier returns (warning: absolute log return above 8 rolling MADs over 30 days), DQ-10 coverage, DQ-11 incomplete candles, DQ-12 cross-timeframe consistency (warning; optional in M1). Errors make the dataset unusable.
- **Dataset ID:** `ds-` + first 16 hex characters of SHA-256 over the canonical text: `instrument_id\ntimeframe\nsource_label\n` followed by `open_time_utc,open,high,low,close,volume\n` for each row (normalized decimal strings). Store `data/datasets/<id>/candles.parquet` and `manifest.json`, then set both files read-only. Creating an existing ID returns the existing manifest unchanged.

### 7.6 Universe and eligibility (`trader.universe`)

For each in-scope instrument at decision time `t` (point in time):

- **support:** the instrument has a market mapping for the dataset's venue (`csv`, `sim`, or the CCXT venue).
- **explicit exclusion:** the asset is not disallowed and not blocked in the registry.
- **liquidity:** median over the last 30 complete UTC days (up to `t`) of daily `sum(volume × close)` must be at least the threshold for the asset's tier.
- **data history:** the number of days of continuous history up to `t` must be at least the threshold; any gap reported by DQ-06 breaks continuity.
- **spread:** no spread provider in M1, so apply `spread.when_no_spread_data` (`not_applicable` in EXP-2026-001).
- Result per asset: `eligible` true or false, criterion outcomes, and reason `ELIGIBILITY_THRESHOLD_UNRESOLVED` if a threshold is `TBD` (the compiler normally blocks this earlier).

### 7.7 Features, regime, strategy, ensemble

- **Features (`features-m1-1.0.0`):** `sma_20`, `sma_50` (simple moving averages of close) and `atr_14` (Wilder ATR on the decision timeframe). Computed from the snapshot window only; `warmup_complete` is false until 51 closed bars exist.
- **Null regime classifier:** `trend_state = unknown`, `volatility_state = unknown`, `method = not_evaluated`, `data_state = stale` if the snapshot is stale, else `ok`; `classifier_id = null_classifier`, `classifier_version = 1.0.0`.
- **`sma_trend` 1.0.0:** at decision time `t` with warm-up complete: emit `buy` if `sma_20[t] > sma_50[t]` and `sma_20[t-1] <= sma_50[t-1]` (rationale `SMA_CROSS_UP`); emit `sell` if `sma_20[t] < sma_50[t]` (rationale `SMA_FAST_BELOW_SLOW`); otherwise nothing. `strength = 1`, `confidence = None`, `expected_horizon = None`, `invalidation = Invalidation(kind="indicator_cross", level=None, reason="SMA_FAST_BELOW_SLOW")`, `sleeve = core`.
- **Pass-through ensemble** (`single_strategy_passthrough`, `ensemble_version 1.0.0`): if `data_state == stale` → `no_trade` with `DATA_STALE`. Flat + buy → `enter_long`. Long + sell (from an owner strategy) → `exit_long`. Flat + sell or long + buy → `hold`. No signal → `hold`.

### 7.8 Risk engine (`trader.risk`)

```python
class RiskEngine:
    version = "1.0.0"
    def evaluate(self, decision: EnsembleDecision, ctx: RiskContext) -> RiskDecision: ...
    def build_order_intent(self, rd: RiskDecision, ctx: RiskContext) -> OrderIntent | None: ...
    def build_protective_stop_intent(self, entry: OrderIntent, fill: ExecutionReport,
                                     rd: RiskDecision, ctx: RiskContext) -> OrderIntent: ...
# RiskContext: compiled profile, position snapshot, market snapshot, feature set, universe snapshot,
#              run controls (kill switch, execution flag), loss state, cooldowns, used idempotency keys,
#              pending orders, cost scenario, asset registry.
```

Only `enter_long` and `exit_long` are evaluated (`hold` and `no_trade` produce no `RiskDecision`). Rules run in order. A failure in RR-01 to RR-12 stops evaluation; the remaining rules are recorded as `not_evaluated`. Rules not applicable to exits are recorded as `not_applicable`.

| Rule | Applies | Check | Failure code |
|---|---|---|---|
| RR-01 | Entry, exit | Compiled profile runnable for the environment; profile not suspended | `PROFILE_NOT_RUNNABLE` |
| RR-02 | Entry, exit | No blockers; in `paper`, no `experiment` or `fixture` provenance | `RISK_CONFIG_UNRESOLVED` |
| RR-03 | Entry, exit | Run kill switch disengaged; `autonomy_mode == paper_autonomous`; environment `execution_enabled` | `KILL_SWITCH_ENGAGED`, `EXECUTION_DISABLED` |
| RR-04 | Entry, exit | Safety constants hold (simulated funds, spot, no leverage, margin, shorting, withdrawals) | `SAFETY_VIOLATION` |
| RR-05 | Entry | Instrument in registry (`ASSET_NOT_SUPPORTED`), spot and in profile scope (`ASSET_NOT_SUPPORTED`), not blocked or disallowed (`ASSET_BLOCKED`), eligible at `t` (`ASSET_INELIGIBLE`) | as listed |
| RR-06 | Entry, exit | Snapshot fresh and quality ok | `STALE_DATA`, `DATA_QUALITY_FAILED` |
| RR-07 | Entry, exit | Idempotency key unused; no pending (unfilled) market order for the instrument (resting protective stops excluded); entries only when flat | `DUPLICATE_ORDER` |
| RR-08 | Entry, exit | Buys within available cash; sells within held quantity | `SPOT_CONSTRAINT_VIOLATION` |
| RR-09 | Entry | `drawdown >= breaker` opens the breaker (latched, `CIRCUIT_BREAKER_OPENED`); open breaker rejects | `CIRCUIT_BREAKER_OPEN` |
| RR-10 | Entry | `(day_start_equity − equity) / day_start_equity × 100 >= daily_loss_limit_pct` starts a lockout until next 00:00 UTC (`DAILY_LOCKOUT_STARTED`) | `DAILY_LOSS_LIMIT` |
| RR-11 | Entry | No active cooldown for `strategy_id|instrument_id` | `COOLDOWN_ACTIVE` |
| RR-12 | Entry | Intraday sleeve signals: sleeve enabled (always disabled in M1) | `INTRADAY_SLEEVE_DISABLED` |
| RR-13 to RR-20 | Entry | Sizing (below) | see below |

**Sizing (entries; all `Decimal`):**

```text
E = equity, C = cash, K = committed cash, P = latest close, B = breaker pct, DD = drawdown pct
m_loss   = schedule multiplier for DD/B: first step with DD/B < drawdown_fraction_of_breaker_below
stop_d   = atr_multiple * atr_14 / P            (or fixed_pct/100)
budget   = E * risk_per_trade_pct/100 * m_loss
N_risk   = budget / stop_d
H_tier   = E * tier_cap_pct/100 - exposure(asset) - pending(asset)
H_spec   = E * spec_total_pct/100 - spec_exposure - spec_pending        (speculative only)
H_total  = E * total_exposure_cap_pct/100 - total_exposure - total_pending
H_cash   = (C - K - E * reserve_low/100) / (1 + fee_rate_pct/100)
N        = min(N_risk, H_tier, H_spec, H_total, H_cash)
if N <= 0: reject (CONCENTRATION_LIMIT | EXPOSURE_LIMIT | RESERVE_LIMIT per binding limit)
RR-19: open positions + pending entries >= max_open_positions -> reject MAX_POSITIONS
P_cons   = P * (1 + slippage_bps/10000)
qty      = round_down(N / P_cons, quantity_step)
RR-20: qty * P_cons < min_notional_usd -> reject SIZE_BELOW_MINIMUM
status   = approved if N == N_risk else modified (binding_constraint)
approved_quantity = qty ; approved_notional_usd = qty * P_cons
```

If `atr_14` is missing (warm-up incomplete), reject with `RISK_CONFIG_UNRESOLVED` and detail `stop_inputs_missing`; this cannot normally happen because the strategy emits nothing before warm-up.

**Exits:** `approved_quantity` = full held quantity; `approved_notional_usd = qty × P × (1 − slippage_bps / 10,000)`.

**Order intents:** `build_order_intent` creates a market intent (entry or exit) with `valid_until_utc = t + timeframe`, `market_data_timestamp_utc` = the snapshot's latest close time, and the idempotency key from §7.3. Entries carry `attached_stop_distance_pct = stop_d × 100`. `build_protective_stop_intent` creates `purpose = protective_stop`, `order_type = stop_market`, `stop_price = fill_price × (1 − stop_d)`, `quantity = filled quantity`, `parent_order_intent_id` = the entry's ID, and the same risk decision, signals, versions, and configuration hash.

**Loss state:** the high-water mark is the maximum equity marked at bar closes since run start. Drawdown = `(hwm − equity) / hwm × 100`. Day-start equity = equity marked at the bar close at 00:00 UTC.

**Cooldown:** after an exit fill (strategy exit or stop), if realized PnL after fees < 0, increment the consecutive-loss count for `strategy_id|instrument_id`; otherwise reset it. When the count reaches the threshold, set the cooldown until `exit time + duration_hours` (`COOLDOWN_STARTED`) and reset the count.

**Run controls (`trader.risk.controls`):** `KillSwitch` (engage(reason, trigger), disengage(reason, by_owner=True), state), `CircuitBreaker`, `DailyLockout`, `Cooldowns`. Automated callers can only engage. The persisted kill switch (`OperationalStore`) appends `KillSwitchState` rows to `data/state/operational.sqlite`.

### 7.9 Execution (`trader.execution`)

```python
class ExecutionAdapter(Protocol):
    adapter_id: str; adapter_version: str
    def validate_order(self, intent: OrderIntent) -> list[str]: ...
    def submit_order(self, intent: OrderIntent) -> ExecutionReport: ...
    def cancel_order(self, order_intent_id: str) -> ExecutionReport: ...
    def get_order(self, order_intent_id: str) -> ExecutionReport: ...
    def list_open_orders(self) -> list[ExecutionReport]: ...
    def get_balances(self) -> dict[str, Decimal]: ...

ALLOWED_ADAPTERS = frozenset({"simulated"})      # registry refuses anything else (ADAPTER_NOT_ALLOWED)

class ExecutionGate:
    def check(self, intent: OrderIntent, rd: RiskDecision | None, ctx: GateContext) -> list[ReasonCode]: ...
```

Gate checks, in order:

- **EG-01:** `rd` exists, has status `approved` or `modified`, and matches the intent's instrument and side; `intent.quantity <= rd.approved_quantity`; `intent.notional_estimate_usd <= rd.approved_notional_usd`. Failure codes `RISK_DECISION_MISSING`, `RISK_DECISION_MISMATCH`, `EXCESSIVE_SIZE`.
- **EG-02:** run kill switch disengaged and execution enabled. Exempt: protective stops of already-filled entries.
- **EG-03:** idempotency key unused (`DUPLICATE_ORDER`).
- **EG-04:** `funds == "simulated"` and adapter in `ALLOWED_ADAPTERS` (`ADAPTER_NOT_ALLOWED`).
- **EG-05:** `valid_until_utc` not passed at submission (`INTENT_EXPIRED`).

Any failure → `ORDER_REJECTED` event, nothing sent to the adapter.

**`SimulatedExecutionAdapter`** (driven by the runner with the current bar):

- Market buy fill = `next_open × (1 + slippage_bps / 10,000)`; market sell fill = `next_open × (1 − slippage_bps / 10,000)`; both clamped to `[bar.low, bar.high]`.
- Stop sell fill = `min(stop_price, bar.open) × (1 − slippage_bps / 10,000)`, clamped to `[bar.low, bar.high]`.
- `fees_usd = fill_qty × fill_price × fee_rate_pct / 100`.
- Orders whose fill bar is missing expire.
- Rejects any intent with `funds != simulated`.
- States: `accepted` on submit; `filled`, `expired`, or `canceled` later. No partial fills in M1.
- `latency_ms = 0` (the delay is modeled as next-bar-open).
- Keeps its own balances for reconciliation.

### 7.10 Portfolio (`trader.portfolio.ledger`)

Cash starts at `paper_capital_usd` (2500). On buy fill: `cash −= qty × price + fees`. On sell fill: `cash += qty × price − fees`. Track average entry price, realized PnL (after both sides' fees), owner strategy IDs, and resting stop price. Mark to market at each close. `committed_cash` = the sum over pending buy intents of `notional_estimate × (1 + fee_rate)`. Reconcile after every fill: ledger cash and quantities must equal adapter balances exactly; a mismatch engages the run kill switch (`RECONCILIATION_FAILED`, then `KILL_SWITCH_ENGAGED`).

### 7.11 Journal (`trader.journal`)

```sql
CREATE TABLE IF NOT EXISTS events (
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL,
  event_type TEXT NOT NULL, event_time_utc TEXT NOT NULL, recorded_at_utc TEXT NOT NULL,
  cycle_id TEXT, correlation_id TEXT, payload_type TEXT NOT NULL,
  payload_schema_version TEXT NOT NULL, payload_json TEXT NOT NULL,
  code_revision TEXT NOT NULL, config_hash TEXT NOT NULL,
  prev_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
  PRIMARY KEY (run_id, seq));
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
```

- File: `data/journal/journal.sqlite`. One transaction per event; commit before returning.
- Genesis `prev_event_hash = "sha256:" + "0" × 64`.
- `event_hash = sha256(prev_event_hash + "\n" + canonical_json(content))`, where `content` contains `seq`, `event_id`, `event_type`, `event_time_utc`, `cycle_id`, `correlation_id`, `payload_type`, `payload_schema_version`, `payload`, `code_revision`, `config_hash` (it excludes `run_id`, `recorded_at_utc`, and `event_hash`). The run's journal root hash is its last `event_hash`.
- `event_time_utc` is simulated time in backtests; `recorded_at_utc` is wall-clock time.
- **Journal before act:** `ORDER_INTENT_CREATED` must be committed before the gate and adapter are called. If the write raises, do not submit; engage the run kill switch (`journal_write_failure`) and fail the run (`RUN_FAILED`, exit 1).
- **`verify(run_id)`** recomputes the chain (`JOURNAL_INTEGRITY_FAILED`, exit 4 on mismatch) and checks D-36 for every `ORDER_INTENT_CREATED`: the referenced `SIGNAL_GENERATED` events exist with strategy and model versions; the `RISK_EVALUATED` event exists with an approved or modified status; `config_hash` equals the run's `PROFILE_COMPILED` hash; `market_data_timestamp_utc` is at or before the decision time and matches a journaled snapshot. Output: `OK <n_events> events, <n_orders> orders traceable, root <hash>`.

### 7.12 Evaluation and report (`trader.evaluation`)

- **Benchmarks** (analytical, R-20): `bm_cash`; `bm_bh_btc` and `bm_bh_eth` (all capital at the first evaluated bar's next open, with that scenario's fee and slippage, held to the end); `bm_ew_btc_eth` (50/50, no rebalancing). All are marked at each decision close in the evaluation window.
- **Metrics** (365-day year, risk-free 0): total return, CAGR, maximum drawdown, volatility, Sharpe-like, Sortino-like, Calmar, closed trades, win rate, profit factor, average holding hours, average exposure %, `fees_usd`, `slippage_cost_usd` (sum over fills of `|fill − reference open| × qty`), rejections by reason code. Daily returns come from equity at 00:00 UTC.
- **Output:** `data/reports/<run_id>/report.json` and `report.md`. Serialize numbers as strings: 8 decimals for ratios, 2 for USD.

```json
{
  "report_schema_version": "1.0.0",
  "run_metadata": {"run_id": "...", "created_at_utc": "...", "code_revision": "..."},
  "disclaimer": "Simulated results on historical data. Not a forecast. Profitability is not guaranteed or implied.",
  "provenance": {"config_hash": "...", "trading_profile": {"id": "balanced-paper", "version": "1"},
                 "risk_profile": {"id": "balanced", "version": "1"}, "experiment_id": "EXP-2026-001",
                 "non_approved_values": [{"field": "...", "value": "...", "provenance": "experiment|hypothesis|fixture", "ref": "UD-nn|H-nn"}]},
  "data": {"datasets": ["ds-..."], "timeframe": "4h", "evaluation_start_utc": "...", "evaluation_end_utc": "..."},
  "costs": {"scenario": "base", "fee_rate_pct": "0.40", "slippage_bps": "10", "min_notional_usd": "10"},
  "strategy": {"strategy_id": "sma_trend", "version": "1.0.0", "metrics": {}},
  "benchmarks": {"bm_cash": {}, "bm_bh_btc": {}, "bm_bh_eth": {}, "bm_ew_btc_eth": {}},
  "comparison": [{"benchmark": "bm_bh_btc", "excess_total_return": "...", "excess_cagr": "..."}],
  "trading": {"order_intents": 0, "fills": 0, "closed_trades": 0, "fees_usd": "0.00",
              "slippage_cost_usd": "0.00", "rejections_by_reason": {}},
  "journal": {"root_hash": "sha256:...", "event_count": 0}
}
```

`report.md` starts with the disclaimer and a **"Values used that are NOT owner-approved"** table, then the comparison table and metrics. Never use words such as "guaranteed", "risk-free profit", or "will earn".

### 7.13 Backtest runner and run outputs

```python
def run_backtest(profile: Path, datasets: list[str], strategy: str, timeframe: str,
                 experiment: Path | None, cost_scenario: str | None,
                 start_utc: datetime | None, end_utc: datetime | None) -> RunResult: ...
```

- `run_id = "run-" + UTC wall time (YYYYMMDDTHHMMSSZ) + "-" + 6 random hex characters` (metadata only; excluded from hashes).
- Journal `RUN_STARTED` (inputs, the persisted kill-switch state), then `PROFILE_COMPILED`. If not runnable, journal `RUN_BLOCKED` with the blockers and exit 3.
- Datasets must cover the instruments in scope at the requested timeframe. Re-verify their hashes (exit 4 on mismatch) and journal `DATASET_VALIDATED`.
- When `--experiment` is given, write `data/experiments/<experiment_id>/runs/<run_id>.json` (`ExperimentRecord`, status `completed`, reproduction command filled in).

### 7.14 CLI (`trader`)

| Command | Behavior |
|---|---|
| `trader version` | Prints the package version and the safety statement "Simulated funds only." |
| `trader profile validate PROFILE [--environment backtest|paper] [--experiment FILE]` | Compiles and prints a summary: runnable, errors, blockers with UD IDs, non-approved values, `config_hash` |
| `trader profile compile PROFILE [--environment] [--experiment] [--out FILE]` | Writes the `CompiledProfile` JSON |
| `trader data synth --instrument ID --timeframe TF --start ISO --end ISO --seed N --start-price P [--daily-quote-volume-usd V]` | Creates a synthetic dataset; prints the dataset ID |
| `trader data import --csv FILE --instrument ID --timeframe TF --source-label NAME` | Creates a dataset from CSV; prints the ID |
| `trader data fetch --exchange NAME --symbol SYM --instrument ID --timeframe TF --start ISO --end ISO` | Optional public OHLCV download (`ccxt` extra) |
| `trader data validate DATASET_ID` | Re-runs integrity and quality checks |
| `trader data list` | Lists datasets |
| `trader backtest run --profile FILE --datasets ID[,ID] --strategy sma_trend --timeframe 4h [--experiment FILE] [--cost-scenario base] [--start ISO] [--end ISO]` | Runs; prints `run_id` and the report path |
| `trader report show RUN_ID [--format md|json]` | Prints the report |
| `trader journal verify RUN_ID` | Verifies the chain and traceability |
| `trader killswitch status|engage --reason TEXT|disengage --reason TEXT` | Persisted kill switch; `disengage` records `changed_by=owner` |

Exit codes: 0 success; 1 unexpected internal error; 2 invalid input (schema, policy, data quality, safety); 3 blocked by unresolved decisions; 4 integrity verification failed.

### 7.15 Logging

JSON lines to stderr and `data/logs/<run_id>.jsonl`, with fields `ts`, `level`, `logger`, `msg`, `run_id`, `cycle_id`, `correlation_id`, `event_type`. Never log secrets (there are none in M1).

---

## 8. Implementation order

Work in this order and keep tests green after each step.

| Step | Backlog | Deliverable | Tests to pass |
|---|---|---|---|
| 1 | BL-001 | Scaffold, `pyproject.toml`, tooling, `.gitignore`, `.env.example`, `BLOCKERS.md`, `docs/spec/`, ADR template and ADR-001 to ADR-018 stubs (titles from `architecture.md` §14) | smoke |
| 2 | BL-002 | Common utilities (clock, IDs, canonical JSON, hashing, Decimal helpers, JSON logging, code revision) | unit |
| 3 | BL-003 | Domain contracts and enums (§7.2, §7.3) | T-47 |
| 4 | BL-004, BL-006 | Extraction script, configuration files, loaders, schema validation of shipped configs | T-02, T-03 |
| 5 | BL-005 | Profile compiler and `trader profile validate|compile` | T-01, T-04 to T-10 |
| 6 | BL-007, BL-008 | Providers, quality checks, dataset store, `trader data ...` | T-11 to T-18 |
| 7 | BL-009 | Registry and eligibility | T-22 (eligibility part) |
| 8 | BL-010 to BL-012 | Features, null regime, `sma_trend`, pass-through ensemble | T-19, T-20 |
| 9 | BL-011 | Benchmarks | T-21 |
| 10 | BL-019, BL-013 | Run controls, persisted kill switch, risk engine | T-22 to T-34, T-45 |
| 11 | BL-014, BL-015 | Execution gate, simulator, ledger, reconciliation | T-24, T-26, T-35, T-36 |
| 12 | BL-016 | Journal store, verify, journal before act | T-37 to T-41 |
| 13 | BL-017, BL-018 | Runner, reports, `trader backtest run`, `trader report show`, experiment run records | T-42 to T-44, T-48 |
| 14 | BL-020 | Safety and neutrality tests, README, demo script, definition-of-done check | T-46, T-47, §11 |

---

## 9. Test cases

### 9.1 Fixtures

- `tests/fixtures/experiments/EXP-0000-001-e2e.yaml`: same structure as EXP-2026-001, with `purpose: test_fixture`, `data_history.min_by_tier.core: 30`, `liquidity.min_by_tier.core: 1`, other values as in EXP-2026-001. Provenance label `fixture`.
- Synthetic datasets with small spans (for example 120 days of 4h bars) and fixed seeds.
- Hand-built candle lists for exact-value tests.
- Risk tests build `RiskContext` objects directly, with `fixture` values; they never edit `configs/risk/*.yaml`.

### 9.2 Catalogue

Run all with `uv run pytest`. "D-47" marks the kickoff's required rejection categories.

| ID | File | Given / When | Then |
|---|---|---|---|
| T-01 | unit/test_profile_compile.py | Shipped profile + EXP-2026-001, backtest | runnable; capital 2500; `funds` simulated; risk profile `balanced`; `config_hash` starts `sha256:` |
| T-02 | unit/test_profile_schema.py | Profiles missing `status`, with wrong types, or with unknown keys | `SCHEMA_INVALID`; CLI exit 2 (**D-47 invalid profiles**) |
| T-03 | safety/test_safety_constants.py | `funds: real`; any of leverage, margin, short selling, withdrawals, transfers, real money true; `instrument_types: [perpetual]`; environment `live` | Rejected; exit 2 (**D-47 invalid profiles**) |
| T-04 | unit/test_profile_policy.py | `risk_profile_id: aggressive` without acknowledgement | `AGGRESSIVE_NOT_ACKNOWLEDGED` |
| T-05 | unit/test_profile_policy.py | Status `draft` or `suspended` (backtest); status `validated` (paper) | `PROFILE_NOT_RUNNABLE` (**D-47 invalid profiles**) |
| T-06 | unit/test_profile_policy.py | BTC both Core and disallowed; instrument `SOL-USD` not in Core or allowlist; fixture values breaking RP-01 (exposure 90 + reserve floor 20) and RP-04 (daily 20 ≥ breaker 15) | `PROFILE_CONTRADICTION`, `RISK_PROFILE_CONTRADICTION` |
| T-07 | unit/test_blockers.py | Shipped profile, backtest, no experiment | Exit 3; blockers include UD-01, UD-02, UD-03, UD-04, UD-12, UD-15, UD-16, UD-17, UD-18; no defaults appear in `effective` |
| T-08 | unit/test_experiment_overlay.py | EXP-2026-001 with `--environment paper` | `EXPERIMENT_PARAMETERS_REJECTED` |
| T-09 | unit/test_experiment_overlay.py | Experiment targeting `global_hard_constraints.leverage_allowed`, `kill_switch.manual_disengage`, or a field already `approved` in a fixture | `EXPERIMENT_PARAMETERS_REJECTED` |
| T-10 | unit/test_profile_compile.py | Compile twice; inspect provenance | Same `config_hash`; core cap provenance `hypothesis` (H-01); experiment fields `experiment`; changing any input changes the hash |
| T-11 | unit/test_quality.py | Two rows with the same `open_time_utc` and different close | DQ-05 error; dataset not created |
| T-12 | unit/test_quality.py | Rows out of order (fixable) and a row at 01:30 for 1h | Ordering warning and sorted; alignment DQ-03 error |
| T-13 | unit/test_quality.py | `high < close`; `low > open`; price 0 | DQ-07 error |
| T-14 | unit/test_quality.py | Naive datetime in CSV and in a `Candle` | `NAIVE_TIMESTAMP` |
| T-15 | unit/test_quality.py | Missing bars | Warning lists the gap; no synthetic fill; snapshot at a missing close is stale |
| T-16 | unit/test_quality.py | Last candle closes after `retrieved_at_utc` | Dropped with a DQ-11 warning |
| T-17 | unit/test_dataset_store.py | Create the same candles twice | Same `dataset_id`; one directory |
| T-18 | unit/test_dataset_store.py | Modify a stored Parquet file (after making it writable in the test) | `load`/`data validate` → `DATASET_INTEGRITY_FAILED`, exit 4 |
| T-19 | unit/test_sma_trend.py | Hand-built series with one cross up and a later cross down | One buy at the cross; sells while below; `SignalCandidate` has no quantity, notional, or stop fields (constructing one with `quantity=` raises) |
| T-20 | unit/test_no_lookahead.py | Hypothesis property: perturb candles after `t` | All signals, features, and decisions at or before `t` unchanged; every `FeatureSet` has `max_input_close_time_utc <= as_of_utc` |
| T-21 | unit/test_benchmarks.py | 5-bar synthetic series, base costs | `bm_bh_btc` final equity equals a hand calculation to the cent; `bm_cash` stays 2500.00; `bm_ew_btc_eth` correct |
| T-22 | unit/test_risk_assets.py | Entry for `DOGE-USD` (not in registry); a blocked asset; a disallowed asset; an asset outside the profile; a non-spot instrument; BTC before 30 days of history (fixture) | `ASSET_NOT_SUPPORTED`, `ASSET_BLOCKED`, `ASSET_INELIGIBLE` (**D-47 unsupported assets**) |
| T-23 | unit/test_risk_stale.py | Snapshot missing the expected latest candle | `STALE_DATA`; no `OrderIntent` (**D-47 stale data**) |
| T-24 | unit/test_execution_gate.py | Intent quantity = approved + one step; intent without a risk decision; intent for another instrument | `EXCESSIVE_SIZE`, `RISK_DECISION_MISSING`, `RISK_DECISION_MISMATCH`; adapter never called (**D-47 excessive sizing**) |
| T-25 | unit/test_sizing_property.py | Hypothesis: random equity, prices, ATR, exposures, caps | Approved notional ≤ every cap headroom and ≤ `N_risk`; reserve floor kept; quantity is a multiple of the step and rounded down (**D-47 excessive sizing**) |
| T-26 | unit/test_duplicates.py | Same decision submitted twice; entry while a market order is pending; entry while already long | `DUPLICATE_ORDER` (**D-47 duplicate orders**) |
| T-27 | unit/test_loss_limits.py | Fixture daily limit 3; equity down 3.1% since 00:00 UTC | Entries `DAILY_LOSS_LIMIT` until next 00:00 UTC; exit approved (**D-47 breached loss limits**) |
| T-28 | unit/test_loss_limits.py | Fixture breaker 15; drawdown 15% | `CIRCUIT_BREAKER_OPENED` once; later entries `CIRCUIT_BREAKER_OPEN` even after recovery; exits allowed (**D-47 breached loss limits**) |
| T-29 | unit/test_loss_limits.py | Drawdowns at 0.2, 0.5, and 0.8 of breaker | Multipliers 1.0, 0.5, 0.25; approved size scales accordingly |
| T-30 | unit/test_disabled_states.py | Run kill switch engaged | Entries and exits rejected `KILL_SWITCH_ENGAGED` at RR-03; an intent built before engagement is rejected at EG-02 (**D-47 disabled execution**) |
| T-31 | unit/test_disabled_states.py | Profile status changed to `suspended` mid-run (fixture) | `PROFILE_NOT_RUNNABLE`; no orders (**D-47 disabled execution**) |
| T-32 | unit/test_disabled_states.py | `autonomy_mode: observe_only`; environment `execution_enabled: false` | `EXECUTION_DISABLED`; signals and decisions journaled; zero intents (**D-47 disabled execution**) |
| T-33 | unit/test_cooldown.py | Three consecutive losing trades (fixture count 3, 24 h) | `COOLDOWN_STARTED`; entries `COOLDOWN_ACTIVE` for 24 h; then allowed |
| T-34 | safety/test_spot_long_only.py | Sell more than held; buy beyond cash | `SPOT_CONSTRAINT_VIOLATION`; ledger never negative |
| T-35 | unit/test_simulator.py | Known bars | Buy fill = open × 1.001 (base), sell = open × 0.999; fee = 0.40% of notional; fills clamped to range; stop gap fills at open; order below $10 rejected; missing next bar → expired |
| T-36 | integration/test_reconciliation.py | Inject an adapter balance mismatch | `RECONCILIATION_FAILED` then `KILL_SWITCH_ENGAGED`; further entries rejected |
| T-37 | unit/test_journal_store.py | Run SQL UPDATE and DELETE on `events` | Both raise (append-only) |
| T-38 | unit/test_journal_verify.py | Verify a clean run; then tamper via a raw copy with the triggers dropped | Exit 0, then exit 4 `JOURNAL_INTEGRITY_FAILED` |
| T-39 | integration/test_traceability.py | Every `ORDER_INTENT_CREATED` in an e2e run | Resolves to signal(s) with strategy and model versions, an approved or modified `RISK_EVALUATED`, `PROFILE_COMPILED` `config_hash`, and a snapshot with matching `market_data_timestamp_utc` (D-36) |
| T-40 | unit/test_journal_before_act.py | Journal raises on `ORDER_INTENT_CREATED` | Adapter `submit_order` not called; `RUN_FAILED`; kill switch engaged |
| T-41 | integration/test_idempotent_rerun.py | Re-run the same cycle on the same state | No second order; `DUPLICATE_ORDER` recorded (**D-47 duplicate orders**) |
| T-42 | e2e/test_vertical_slice.py | CLI: synth BTC and ETH (4h, 400 days); validate; backtest with the EXP-0000-001 fixture; report show; journal verify | Exit codes 0; report has all §7.12 sections; four benchmarks; rejections table; non-approved values listed; logs contain `run_id` and `correlation_id` |
| T-43 | e2e/test_determinism.py | Run T-42 twice | Identical journal root hashes; identical `report.json` except `run_metadata` |
| T-44 | e2e/test_blocked_run.py | `backtest run` without an experiment | Exit 3; `RUN_BLOCKED` journaled with UD IDs; zero `ORDER_INTENT_CREATED` |
| T-45 | integration/test_killswitch_cli.py | `engage --reason`, `status`, new process `status`, `disengage --reason` | State persists across processes; history appended; disengage records owner and reason |
| T-46 | safety/test_no_forbidden_capabilities.py | AST scan of `src/` | No function, method, or class definitions and no calls whose names contain `withdraw`, `transfer`, `leverage`, `margin`, `create_order`, `fetch_balance`, or `private_`; the only permitted occurrences of these words are the `*_allowed` constant fields (always false) and docstrings; no `apiKey` or `secret` assignments; adapter allowlist equals `{"simulated"}` |
| T-47 | safety/test_domain_neutral.py | Import graph of `trader.domain` | Only stdlib and pydantic modules |
| T-48 | e2e/test_report_language.py | Generated report files | Disclaimer present; provenance banner lists experiment and hypothesis values; no "guarantee", "risk-free", or "will earn" |

---

## 10. Commands that must work at completion

### 10.1 From a fresh checkout

```bash
uv sync
uv run ruff check .
uv run mypy src
uv run pytest
uv run trader version

# Fail-closed demonstration (expected exit code 3, lists UD IDs)
uv run trader profile validate configs/profiles/balanced-paper.yaml --environment backtest

# Paper environment refuses experiment values (expected exit code 2)
uv run trader profile validate configs/profiles/balanced-paper.yaml --environment paper \
  --experiment experiments/EXP-2026-001-vertical-slice.yaml

# Runnable research configuration (expected exit code 0)
uv run trader profile validate configs/profiles/balanced-paper.yaml --environment backtest \
  --experiment experiments/EXP-2026-001-vertical-slice.yaml

# Data (prints dataset IDs)
uv run trader data synth --instrument BTC-USD --timeframe 4h --start 2023-01-01T00:00:00Z \
  --end 2026-01-01T00:00:00Z --seed 42 --start-price 30000
uv run trader data synth --instrument ETH-USD --timeframe 4h --start 2023-01-01T00:00:00Z \
  --end 2026-01-01T00:00:00Z --seed 43 --start-price 2000
uv run trader data list

# Vertical slice (evaluation starts after 365 days of history for eligibility)
uv run trader backtest run --profile configs/profiles/balanced-paper.yaml \
  --experiment experiments/EXP-2026-001-vertical-slice.yaml \
  --datasets <BTC_DATASET_ID>,<ETH_DATASET_ID> --strategy sma_trend --timeframe 4h \
  --start 2024-01-01T00:00:00Z
uv run trader report show <RUN_ID>
uv run trader journal verify <RUN_ID>

# Kill switch
uv run trader killswitch status
uv run trader killswitch engage --reason "drill"
uv run trader killswitch disengage --reason "drill complete"
```

### 10.2 One-command demo

`uv run python scripts/demo_vertical_slice.py` runs the data, validate, backtest, report, and verify steps above, captures the IDs, and prints the report path. It must succeed on a machine with no network access.

---

## 11. Definition of done (M1)

All of the following are true:

1. Every command in §10 behaves as stated, from a fresh checkout, with no network access and no secrets.
2. `uv run pytest` passes T-01 to T-48. Coverage is at least 95% (branches) for `trader.risk` and `trader.execution` and at least 85% overall.
3. `uv run ruff check .` and `uv run mypy src` are clean; `trader.domain` and `trader.risk` pass mypy strict.
4. The D-47 categories are each proven by passing tests: invalid profiles (T-02 to T-05), unsupported assets (T-22), stale data (T-23), excessive sizing (T-24, T-25), duplicate orders (T-26, T-41), breached loss limits (T-27, T-28), disabled execution states (T-30 to T-32).
5. The slice report compares `sma_trend` with cash, buy-and-hold BTC, buy-and-hold ETH, and equal-weight, and shows returns, fees, slippage, maximum drawdown, trades, and rejections by reason code.
6. `trader journal verify` passes on every e2e run and proves D-36 traceability for every order.
7. No configuration `TBD` was changed; no default risk value exists in code; `BLOCKERS.md` lists any blocker found (or states "None").
8. No real-money, leverage, margin, short-selling, withdrawal, transfer, or live-order capability exists (T-46).
9. `README.md` documents setup, the commands in §10, the safety boundary, and where the specification lives.
10. ADR stubs exist for ADR-001 to ADR-018; any implementation decision of your own is recorded as ADR-019 onward.

---

## 12. Blocker protocol

When a risk requirement is missing or a safety-relevant point is ambiguous: **stop that piece of work, keep the system fail-closed, document it, and continue with independent work.** Never bypass a check, invent a value, or weaken a test.

`BLOCKERS.md` template:

```markdown
# Blockers

## BLK-001: <short title>
- Date (UTC):
- Backlog item / test:
- Missing decision or requirement: (for example `limits.daily_loss_limit_pct` for paper, UD-02)
- Why it blocks:
- What I did instead: (for example kept TBD; the run exits 3 with the UD ID; added a test)
- What I did NOT do: (invent a value / bypass the check / add a live capability)
- Owner action needed:
- Reference: docs/spec/product-requirements.md section 10 (UD-nn)
```

Known, expected blockers that are **not** M1 failures (do not try to resolve them): paper activation and forward paper sessions (UD-01 to UD-05, UD-12, UD-15 to UD-20), Conservative and Aggressive values (UD-13), intraday sleeve (UD-14), Major and Speculative lists (UD-06).

---

## 13. Explicitly out of scope (do not implement)

- Any real-money trading, live order placement, private exchange endpoints, API keys, or order placement outside the simulated adapter.
- Leverage, margin, short selling, derivatives trading, withdrawals, transfers.
- Automatic promotion of strategies or models; any LLM or ML in the decision path.
- Forward paper sessions, schedulers, dashboards, web APIs, conversational interfaces, hosted deployment, Docker (these come after M1).
- Freqtrade or FreqAI dependencies (a later spike, BL-032).
- High-frequency or latency-sensitive logic; minute-level strategies.

---

## 14. Decision references used in code comments

D-02, D-03 (simulated funds only; no leverage or withdrawals), D-04 ($2,500), D-05 and D-07 (objective; no guaranteed profit), D-06 and D-09 (profile selection), D-10 to D-14 (hybrid risk, final authority), D-16 (1h and 4h), D-25 and D-26 (eligibility and tiers), D-29 (pipeline), D-33 to D-36 (autonomous paper execution, kill switch, traceability), D-44 (framework-neutral contracts), D-46 and D-47 (slice and required tests), H-01 to H-04 (Balanced caps), UD-01 to UD-21 (unresolved; never default). Full registers: `docs/spec/product-requirements.md` §3.
