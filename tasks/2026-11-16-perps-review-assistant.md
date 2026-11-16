# 2026-11-16: AI review assistant with role-based reviewers (owner request, ADR-039)

- [x] Deterministic fact pack (state, day events, trades, settings, market facts)
- [x] Six roles with structured outputs; analysts independent; skeptic; lead editor
- [x] Code checks every proposal against the config rules; reports only, never edits
- [x] `trader review run|show|watch`, Compose `review`, RUNBOOK 7a, `configs/assistant.yaml`
- [x] Tests with a fake client (no API calls)
- [ ] Owner: add `ANTHROPIC_API_KEY` to `.env` on the server, start `review` (RUNBOOK 7a)
- [ ] First live review: check cost and quality; tune effort per role if needed
- [ ] After ADR-038 (PR #41) is merged: share one account list between the paper CLI and review
