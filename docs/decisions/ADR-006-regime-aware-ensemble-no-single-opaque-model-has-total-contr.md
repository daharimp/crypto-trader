# ADR-006: Regime-aware ensemble; no single opaque model has total control

- **Status:** Accepted (D-29, D-30)
- **Decision:** The nine-stage pipeline in §7.2. Every model output passes through the ensemble contract and the risk engine.
- **Consequence:** M1 implements pass-through stages so the pipeline shape is stable.

Source: `docs/spec/architecture.md` §14.
