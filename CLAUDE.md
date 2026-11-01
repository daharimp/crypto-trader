# CLAUDE.md

### Project awareness
- Read `PLANNING.md` and `TASK.md` first; the controlling spec is `docs/spec/` (start with
  `code-session-handoff.md` and `execution-plan.md`).
- Add new tasks to `TASK.md` with the date; mark them done when finished; record discoveries
  under "Discovered During Work".

### Non-negotiable safety rules (docs/spec/code-session-handoff.md §0.1)
- Simulated funds only: no real-money, live orders, leverage, margin, shorting, derivatives
  trading, withdrawals, transfers, private endpoints, or API keys, in any form.
- Deterministic risk code has final authority; strategies never size orders.
- Never replace `TBD` values or invent risk defaults. Missing values must fail closed (exit 3).
- If blocked, log it in `BLOCKERS.md`, stay fail-closed, never weaken a test or check.
- `trader.domain` may import only the stdlib and Pydantic.
- No guaranteed-profit language anywhere.

### Tooling
- Use `uv`: `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`,
  `uv run mypy src`.
- Python 3.11+, Pydantic v2, type hints, Google-style docstrings, files under 500 lines,
  `# Reason:` comments for non-obvious logic.
- Tests live in `tests/` (unit, integration, e2e, safety): at least an expected case, an edge
  case, and a failure case for new features.
- Record your own implementation decisions as ADRs (`docs/decisions/ADR-0NN-*.md`).
