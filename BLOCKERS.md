# Blockers

**Open blockers in the code: none.** No risk value was invented and no check was bypassed.

## Owner decisions still open

| ID | What is missing | Needed before | Current behavior |
|---|---|---|---|
| UD-22 | Values approved 2026-11-02 ($250 cap, 42 paper cycles). Still missing: the owner's written **acknowledgement** in `configs/live/authorization.yaml` | Any live session | `live` refused: exit 2 (`LIVE_NOT_ACKNOWLEDGED`) |

Resolved on 2026-11-01: UD-01 to UD-21 (record: `docs/spec/product-requirements.md` §10.2;
ADR-022, ADR-023). UD-14 is resolved as "no intraday trading in V1" and stays `TBD` by design.

## Owner actions for going live (`docs/operations/RUNBOOK.md`)

1. Provision the server, start the paper session, create the API key (no withdrawals), run
   preflight, set UD-22, activate live.

## Not verifiable from this environment

- Real Kraken **public** data was verified on 2026-11-02 (markets, minimums, candles, clock,
  eligibility, one real paper cycle). Private endpoints (orders, balances) need the owner's
  key: covered by a fake exchange in tests and by `trader live preflight` on the server,
  which validates the stop-loss order shape.
- ETH/USD median daily volume on Kraken was $55.7M, just above the $50M Core threshold; in a
  quiet month ETH becomes ineligible and the bot trades BTC only (fail closed, as approved).
- Docker image build (Docker Hub rate-limited here): the frozen production install was
  verified; build on the server with `docker compose build`.

## Perps (ADR-025), added 2026-11-02

| Activity | Needs | Current behavior |
|---|---|---|
| Any `trader perps` backtest or paper run | UD-23 (starting collateral, venue costs and limits, owner risk limits) in `configs/perps/jupiter.yaml` | Exit 3, `PERPS_CONFIG_UNRESOLVED` lists every key |
| Live Jupiter prices | Network access to `jup.ag` from the environment | `PRICE_UNAVAILABLE`, exit 3 |
| Real-money perps | A new ADR and gates; not built | Impossible: `mode` is `Literal["paper"]` |
