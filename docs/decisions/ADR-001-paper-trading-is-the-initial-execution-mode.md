# ADR-001: Paper trading is the initial execution mode

- **Status:** Accepted
- **Decision:** The MVP executes only through dry-run, paper, or sandbox environments with simulated funds (D-02).
- **Reason:** Enables end-to-end testing without exposing capital while order state, retries, risk rules, and monitoring are immature.
- **Consequence:** Paper results may differ from live execution; production readiness requires separate analysis.

Source: `docs/spec/architecture.md` §14.
