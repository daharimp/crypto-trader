# Changelog

All notable changes are recorded here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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

### Changed
- Owner decisions UD-01 to UD-22 resolved (risk profiles v2, eligibility v3, profile v4).
- `ccxt` is now a required dependency.

## [0.1.0] - 2026-11-01

### Added
- M1 vertical slice: profile compiler with fail-closed blockers, data pipeline with quality
  checks, `sma_trend` baseline, deterministic risk engine (RR-01 to RR-20), execution gate,
  simulator, hash-chained journal, benchmarks and reports, kill switch, and the M1 test suite.
