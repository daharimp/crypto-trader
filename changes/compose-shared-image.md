### Fixed
- `docker compose build` now refreshes the code for every service: all services run one
  image, `crypto-trader:local`, built once by `paper`, so the profile-gated `cli`, `builder`,
  and `live` services can no longer run old code after an update (ADR-036). RUNBOOK 8a gives
  the update steps and the one-time removal of the old per-service images.
