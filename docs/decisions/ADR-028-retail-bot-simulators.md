# ADR-028: Order-based simulators for retail bot styles (grid, DCA)

- **Status:** Accepted (2026-11-10; owner asked to test Pionex/Cryptohopper-style bots on our
  own data before deciding whether to run one)
- **Context:** Pionex's grid bot and Cryptohopper's DCA bot rest limit orders and fill
  inside a bar. The research lab (ADR-027) models a position decided at a bar's close and
  filled at the next open, which cannot represent those fills.
- **Decision:**
  1. `trader.research.bots` simulates three bot styles on hourly candles: an arithmetic
     spot grid (fixed range or rebuilt on a schedule), a DCA bot with safety orders and a
     take-profit, and plain weekly DCA as a benchmark.
  2. Each bar is walked along an assumed path (open, nearer extreme, farther extreme, close);
     every order line crossed fills at its own price with the maker fee; market orders pay
     the taker fee plus slippage. Accounting is long-only, unleveraged, cash-limited.
  3. Two research cost sets: Kraken (0.25% maker, 0.50% taker incl. slippage, as last known)
     and Pionex (0.05% maker, 0.10% taker incl. slippage). Both are research assumptions to
     verify, not risk values.
  4. Research only: never imported by the trading pipeline. A bot style reaches paper trading
     only as a registered strategy class with tests, through the risk engine and the gates.
- **Consequences:** The intrabar path is a guess; when a bar touches several lines both ways
  the true order is unknown, so results for tight grids are approximate. Fills at exactly the
  line price ignore queue position (optimistic for grids). Hourly data must be downloaded with
  `scripts/fetch_coinbase_history.py ... 1h`.
