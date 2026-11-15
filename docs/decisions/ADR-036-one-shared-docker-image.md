# ADR-036: One shared Docker image for every compose service

- **Status:** Accepted (2026-11-14; deployment only)
- **Context:** `x-trader` in `docker-compose.yml` had `build: .` and no `image:`, so Compose
  gave each service its own image (`crypto-trader-<service>`). A plain `docker compose build`
  skips services behind `profiles:` (`cli`, `builder`, `live`). On 2026-11-14 the owner
  updated to 6eb5cf3 and rebuilt; `docker compose run --rm cli perps paper status` answered
  `No such command 'paper'` because `crypto-trader-cli` still held pre-perps code. The same
  could leave `live` running old code after an update.
- **Decision:**
  1. Every service uses `image: crypto-trader:local` with `pull_policy: never`.
  2. Only `paper` (not profile-gated) has `build: .`. Compose v5.6.1 makes one build target
     per service that has `build` (`pkg/compose/build_bake.go`), so a shared `build` on all
     six would send six identical targets for one tag; one build owner builds and tags once.
  3. `pull_policy: never`: with `build` plus `image` and no policy, the Compose spec
     (`build.md`, "Using build and image") pulls first and builds only if the pull fails, so a
     missing local image would make Compose ask Docker Hub for `crypto-trader:local`.
  4. `tests/safety/test_deploy_config.py` fails if any service uses another image or pull
     policy, if more or less than one service builds, or if the build is profile-gated.
- **Reason:** one `docker compose build` refreshes the code for every service, so a
  profile-gated service cannot silently run old code.
- **Consequence:** no service's permissions change: the live profile gate, read-only config
  mounts, the localhost-only dashboard port, and the builder as the only config writer stay
  (and are tested). `docker compose run --rm cli ...` no longer builds an image on its own; on
  a server that has never built, it answers `No such image` until `docker compose build` runs.
  Old `crypto-trader-<service>` images are removed once by hand (RUNBOOK section 8a).
- **References:** ADR-023, ADR-024, ADR-026, ADR-031; RUNBOOK sections 1, 2c, 8a.
