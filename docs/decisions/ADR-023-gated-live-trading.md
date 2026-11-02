# ADR-023: Gated real-money spot trading on Kraken

- **Status:** Accepted (owner decision, 2026-11-01; amends D-02/D-03, SAFE-01, ADR-001)
- **Context:** The owner's goal is a bot that trades real money automatically, live by
  Monday 2026-11-02, on Kraken (UD-20), hosted on a cloud server (UD-09). The original
  boundary was paper only.
- **Decision:** add an environment `live` that sends real spot orders to Kraken, available
  only when **all** of these hold, each checked on every start and every cycle:
  1. The trading profile permits `live` and sets `real_money_enabled: true` (the two must
     agree), and its status is `active`.
  2. `configs/live/authorization.yaml` is owner-approved: `max_capital_usd` and
     `min_paper_cycles_before_live` (UD-22, `TBD` = exit 3) plus a written acknowledgement.
  3. The profile version has completed at least `min_paper_cycles_before_live` forward paper
     cycles (recorded per profile version).
  4. An owner activation record exists for `live` for this exact profile content
     (`trader profile activate`). Any edit invalidates it.
  5. The API keys come from environment variables on the server; preflight
     (`trader live preflight`) validates permissions and order shapes without trading.
- **Unchanged (still impossible by construction):** leverage, margin, short selling,
  derivatives, withdrawals, transfers (`Literal[False]` fields; parameter allowlist in the
  adapter; T-46). Strategies still never size; RR-01 to RR-20 and EG-01 to EG-05 still decide
  every order. Experiment and fixture values are still refused outside backtests.
- **Live-only protections:** managed cash = `min(USD balance, cap)`; per-order cap; resting
  stop-loss at Kraken after every entry fill; fees charged in USD (`fciq`) so balances
  reconcile; deterministic `userref` to recover from timeouts without duplicates;
  reconciliation against Kraken with a lot-size tolerance (UD-17); kill switch on
  reconciliation mismatch, missing stop, clock skew > 5 s, 3 stale cycles, 3 exchange errors,
  mid-session config change, or any session error. Owner flatten (UD-19 D) works with the
  kill switch engaged.
- **Consequences and risks:** real losses are possible. The strategy has no real-data
  evidence yet; the owner chose to proceed with a short paper period, so the capital cap is
  the main control. Kraken serves only 720 candles per timeframe, so eligibility uses daily
  candles (about 2 years) and signals use 4h candles (120 days). The Kraken spot stop-loss
  order shape is validated by preflight on the owner's account.
