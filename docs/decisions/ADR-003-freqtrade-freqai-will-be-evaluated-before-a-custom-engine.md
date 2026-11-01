# ADR-003: Freqtrade/FreqAI will be evaluated before a custom engine

- **Status:** Proposed
- **Decision:** Prototype using the framework's backtesting/dry-run capabilities, then replace only components that create a demonstrated limitation.
- **v0.2 recommendation (R-03):** Implement the M1 slice with a minimal in-house deterministic bar-replay simulator behind the `ExecutionAdapter` interface, and run a time-boxed Freqtrade spike (BL-032) that reproduces the buy-and-hold and `sma_trend` results on the same datasets. Adopt Freqtrade as an adapter or cross-check if the spike shows a clear benefit.
- **Reason:** Accelerates development and creates a usable baseline, while keeping the risk engine authoritative and contracts framework-neutral.
- **Consequence:** The internal domain contracts remain framework-neutral; the owner decides this ADR after BL-032.

Source: `docs/spec/architecture.md` §14.
