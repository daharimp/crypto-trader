# ADR-002: LLM output cannot directly create executable orders

- **Status:** Accepted (amended by ADR-008 in v0.2)
- **Decision:** LLM output is limited to proposed profiles, explanations, and research assistance. It must pass schemas and deterministic policy checks. v0.2 amendment: AI and models may also directly influence the D-31 areas through typed contracts (`RegimeAssessment`, `EnsembleDecision`, asset ranking), but still cannot create orders or set any D-32 item.
- **Reason:** LLM output can be inconsistent and should not control financial side effects directly.
- **Consequence:** More explicit contracts and adapters are required, but behavior is testable and auditable.

Source: `docs/spec/architecture.md` §14.
