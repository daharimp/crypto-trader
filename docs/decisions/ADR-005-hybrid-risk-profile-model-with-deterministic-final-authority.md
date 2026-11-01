# ADR-005: Hybrid risk-profile model with deterministic final authority

- **Status:** Accepted (D-08 to D-14)
- **Decision:** The owner selects Conservative, Balanced, or Aggressive (initially Balanced). The system adapts only inside the selected profile's boundaries. Loss handling is hybrid (reassess, reduce size, hard overrides, circuit breaker). Deterministic code has final authority; AI and ML may recommend but not bypass hard limits.
- **Consequence:** All limits live in versioned `RiskProfile` files; unresolved values are `TBD` (UD-01 to UD-04, UD-12 to UD-19).

Source: `docs/spec/architecture.md` §14.
