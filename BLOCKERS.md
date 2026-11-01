# Blockers

**Open blockers in the code: none.** No risk value was invented and no check was bypassed.

## Owner decisions still open

| ID | What is missing | Needed before | Current behavior |
|---|---|---|---|
| UD-22 | Live capital cap and minimum paper cycles in `configs/live/authorization.yaml`, plus the written acknowledgement | Any live session | `live` refused: exit 3 (TBD) / exit 2 (no acknowledgement) |

Resolved on 2026-11-01: UD-01 to UD-21 (record: `docs/spec/product-requirements.md` §10.2;
ADR-022, ADR-023). UD-14 is resolved as "no intraday trading in V1" and stays `TBD` by design.

## Owner actions for going live (`docs/operations/RUNBOOK.md`)

1. Allow `api.kraken.com` in this cloud environment's network settings if you want Claude to
   test against real Kraken data (it is currently blocked here).
2. Provision the server, start the paper session, create the API key (no withdrawals), run
   preflight, set UD-22, activate live.

## Not verifiable from this environment

- Real Kraken API behaviour (network blocked here): covered by a fake exchange in tests and by
  `trader live preflight` on the owner's server, which validates the stop-loss order shape.
- Docker image build (Docker Hub rate-limited here): the frozen production install was
  verified; build on the server with `docker compose build`.
