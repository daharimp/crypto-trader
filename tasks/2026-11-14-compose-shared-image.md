# 2026-11-14: One Docker image for every service (owner report: `perps paper` missing in cli)

- [x] Confirm the cause: profile-gated `cli` kept its own stale `crypto-trader-cli` image
- [x] `docker-compose.yml`: shared `crypto-trader:local`, `pull_policy: never`, one build (ADR-036)
- [x] Safety tests: shared image, single ungated build, no registry pull, builder-only config writes
- [x] RUNBOOK sections 1, 2c, 8a: update steps and one-time cleanup of old images
- [ ] Owner, on the server: `git pull`, `docker compose build`,
      `docker compose up -d paper perps dashboard`, then `docker compose run --rm cli perps paper status`
- [ ] Owner, once: remove the old `crypto-trader-<service>` images (RUNBOOK 8a)
