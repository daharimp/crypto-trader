### Added
- Hands-off server operations (ADR-047): `scripts/ops/autodeploy.sh` deploys main within
  about 5 minutes and never starts `live`; `scripts/ops/watchdog.sh` and the new
  `trader ops health` command check containers, errors, stops, freshness and drawdown every
  15 minutes and alert only on new or changed problems; `scripts/ops/push_status.sh` pushes
  status and reports to the private `crypto-trader-ops` repo for scheduled reviews.
  One-time setup: `scripts/ops/install.sh` (RUNBOOK 8b).
