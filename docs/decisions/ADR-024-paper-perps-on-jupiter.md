# ADR-024: Paper-only perpetual futures research on Jupiter Perps

- **Status:** Accepted (owner decision, 2026-11-01; amends ADR-023 "never add leverage,
  margin, shorting, derivatives" for paper research only)
- **Context:** The owner prefers to trade on Jupiter (Solana) and wants perpetuals, with
  long and short positions and leverage. The existing pipeline is spot, long-only, cash
  never below zero, and ADR-023 forbids leverage and shorting everywhere.
- **Decision:**
  1. Add an isolated package `trader.perps` with its own position model, deterministic risk
     checks and sizing, paper simulator (open/close fees, hourly borrow fees, liquidation),
     a historical replay, and a read-only Jupiter Price API reader. The spot pipeline,
     its `Literal[False]` safety constants, and every ADR-023 live gate are unchanged.
  2. **Paper only.** `mode` is `Literal["paper"]`. The package never builds, signs, or sends
     a transaction, never reads a wallet key, and makes only HTTP GETs to a public price
     endpoint. T-46 now allows the words leverage/margin only inside `trader/perps/`, and a
     new safety test enforces the paper-only rule for that package.
  3. **No invented values.** Starting collateral, venue costs, the venue's maintenance
     requirement and leverage ceiling, and the owner's risk limits (max and target leverage,
     collateral per position, total size, minimum liquidation distance, max positions, daily
     loss limit) are `TBD` under **UD-23**. Every perps command exits 3 until all are
     approved with approver and date. Venue values must be checked against Jupiter's
     current documentation before approval.
  4. Strategies only say long, short, or flat. `size_open` alone sizes (collateral = equity
     x cap, size = collateral x target leverage, rounded down), and `check_open` lists every
     failed rule (`PERP_*` reason codes).
  5. Research signal `sma_stance` (long above, short below SMA 20/50) fills at the next bar
     open; liquidation is checked against each bar's adverse extreme; liquidation loses the
     whole collateral. All three are deliberately conservative.
- **Not decided here (needs a later ADR):** any real-money perps trading on Jupiter. That
  would need a Solana wallet whose key can move every asset in it (unlike a Kraken key
  without withdrawal rights), transaction signing, Jupiter's keeper-based request model,
  and gates at least as strict as ADR-023's, plus a forward paper track record for perps.
- **Consequences:** perps results are simulations with an approximate venue model; they
  are not a forecast and do not guarantee profit. This cloud environment currently blocks
  `jup.ag`, so live price reads fail closed (`PRICE_UNAVAILABLE`) until the host is allowed.
