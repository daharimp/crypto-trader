## What and why

<!-- What does this change, and why? Link the task (`tasks/`) and any UD/ADR/BL IDs. -->

## How it was tested

<!-- Commands run and results (pytest, demo, paper session, preflight). -->

## Safety checklist

- [ ] No leverage, margin, short selling, derivatives trading, withdrawal, or transfer code.
- [ ] Live gates, the capital cap, and the adapter parameter allowlist are unchanged (or the
      change is an owner decision recorded in an ADR).
- [ ] No invented risk values; anything unresolved stays `TBD` and fails closed.
- [ ] Configuration edits carry a version increment and approval fields.
- [ ] No secrets, keys, `.env` contents, or webhook URLs in code, configs, logs, or this PR.
- [ ] Tests added or updated (expected, edge, and failure cases).
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, and
      `uv run pytest` pass.
- [ ] Docs updated (README, RUNBOOK) where behaviour changed; a note in `changes/` and a
      task file in `tasks/` (not edits to `CHANGELOG.md` or `TASK.md`).
