# ADR-018: Append-only, hash-chained journal with journal-before-act

- **Status:** Proposed (R-05)
- **Decision:** SQLite triggers forbid updates and deletes; each event stores the previous event's hash; order intents are written before submission.

Source: `docs/spec/architecture.md` §14.
