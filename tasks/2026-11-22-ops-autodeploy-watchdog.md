# 2026-11-22: Hands-off monitoring and auto-deploy (owner request)

- [x] Read-only `trader ops health` with de-duplicated alerts (ADR-047)
- [x] `scripts/ops/` auto-deploy, watchdog, status push, install
- [x] RUNBOOK 8b setup steps
- [ ] Owner: create the private repo `daharimp/crypto-trader-ops`
- [ ] Owner: run `scripts/ops/install.sh` on the server and add the printed deploy key
- [ ] Scheduled tasks: 4-hourly health check and daily review read the ops repo
