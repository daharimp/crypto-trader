# Changelog

All notable changes are recorded here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow
[Semantic Versioning](https://semver.org/).

## Unreleased (2026-11-03): profile builder

- `trader profile build`: one question per risk setting, options from the spec (UD-01..UD-17)
  for the chosen preset, custom values only inside the spec's range; writes a named risk
  profile, trading profile, and spec sheet after a clean compile (ADR-024).
- Web form `docs/profile-builder/index.html` (same question bank) produces `answers.json` for
  `trader profile build --answers`.
- Owner-named risk profiles; acknowledgement required for every explicitly selected profile;
  risk file ID must match its file name.
- `trader session run` defaults strategy and timeframe from the profile's `trading_spec`.
- `TRADER_PROFILE` in `.env` selects the profile the Docker `paper`/`live` services run.
- `trader research compare --timeframe 1h`; EXP-2026-004 part 1 (1h screen).

## [Unreleased]

### Added
- Research: `trader.research.bots` simulates grid, DCA-with-safety-orders, and plain DCA bots
  on hourly candles with maker/taker fees (ADR-028).
- `trader perps paper run|status` and a `perps` compose service: a forward paper perps
  session that goes long in uptrends and short in downtrends on live prices (ADR-031).
- `trader research snapshot`: live Kraken state per coin compared with what happened after
  similar states in history, in dollars with 90% ranges (ADR-029).
- Gated live spot trading on Kraken (ADR-023): `live` environment, live authorization
  (capital cap and paper prerequisite, UD-22), profile activation (`trader profile activate`).
- Forward paper and live sessions (`trader session run|status|flatten|reset-breaker`) with
  persisted state, restart recovery, and automatic halts (reconciliation, missing stop, clock
  skew, stale data, exchange errors, configuration change).
- Kraken adapter: capped market orders, resting stop-loss after every fill, fees in USD,
  duplicate-safe timeout recovery; validate-only preflight (`trader live preflight`).
- Webhook alerts (ntfy, Slack, Discord); Dockerfile and docker-compose deployment; runbook.
- Universe: SOL and XRP (Major), SUI (Speculative) alongside BTC and ETH (Core).
- Repository setup: CI, Dependabot, issue and pull request templates, community files.
- Backtests accept daily eligibility datasets (`--eligibility-datasets`); equal-weight
  universe benchmark (`bm_ew_universe`).
- EXP-2026-002: first real-data test on Kraken (no evidence of an edge; see
  `docs/experiments/`).
- Comparison strategies (BL-022): `tsmom`, `mean_reversion`, `volatility_breakout`, and the
  research-only `random_entry` control; feature set `features-m2`.
- Post-only limit orders in the simulator (cost scenarios `base_maker`, `stress_maker`);
  live trading refuses them for now. Preflight reports the account's real fee tier.
- `trader data import-kraken` for Kraken's downloadable OHLCVT history and
  `trader research compare` (strategies x windows x costs with a matched random control).
- EXP-2026-003: strategy comparison on real data (no edge; limit orders cut fees by a third).

### Changed
- Owner decisions UD-01 to UD-22 resolved (risk profiles v2, eligibility v3, profile v4).
- `ccxt` is now a required dependency.

## [0.1.0] - 2026-11-01

### Added
- M1 vertical slice: profile compiler with fail-closed blockers, data pipeline with quality
  checks, `sma_trend` baseline, deterministic risk engine (RR-01 to RR-20), execution gate,
  simulator, hash-chained journal, benchmarks and reports, kill switch, and the M1 test suite.
