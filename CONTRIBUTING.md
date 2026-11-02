# Contributing

This is a private, proprietary project (see [LICENSE](LICENSE)). Changes are made by the
owner or by people and AI agents working for the owner. This guide is how that work is done.

## Ground rules (non-negotiable)

Read [`CLAUDE.md`](CLAUDE.md) and [ADR-023](docs/decisions/ADR-023-gated-live-trading.md)
first. In short:

- **Paper by default.** Real-money spot orders exist only in the gated `live` environment
  through `src/trader/execution/adapters/kraken_live.py`. Never weaken a live gate, the
  capital cap, or the adapter's parameter allowlist.
- **Never add** leverage, margin, short selling, derivatives trading, withdrawals, or
  transfers. The safety tests (`tests/safety/`) scan for them.
- **Never invent risk values.** `TBD` means an unresolved owner decision; runs that need it
  must fail closed (exit 3). Owner decisions are recorded in
  `docs/spec/product-requirements.md` §10.2.
- **Secrets** (Kraken keys, webhook URLs) live only in `.env` on the server. Never commit
  them, paste them into issues, or log them.
- **Never weaken a test or check to make progress.** Record blockers in
  [`BLOCKERS.md`](BLOCKERS.md) instead.

## Development setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run ruff check .          # lint
uv run ruff format .         # format (black-compatible)
uv run mypy src              # types (strict for trader.domain and trader.risk)
uv run pytest                # full suite, offline, no keys needed
uv run python scripts/demo_vertical_slice.py   # end-to-end demo
```

CI (`.github/workflows/ci.yml`) runs the same checks on every pull request and on `main`.

## Making a change

1. Read [`PLANNING.md`](PLANNING.md) and [`TASK.md`](TASK.md); add your task to `TASK.md`
   with the date.
2. Branch from `main`. Keep each pull request to one purpose.
3. Write tests: at least one expected case, one edge case, and one failure case. Tests live
   under `tests/` (`unit`, `integration`, `e2e`, `safety`).
4. Follow the conventions: type hints, Google-style docstrings, files under 500 lines,
   `# Reason:` comments for non-obvious logic, `Decimal` for money, UTC-aware datetimes.
5. Record your own design decisions as ADRs (`docs/decisions/ADR-0NN-*.md`).
6. Fill in the pull request template; every safety checklist item must be true.

## Changing configuration

Profiles, risk profiles, eligibility rules, and the live authorization are versioned
records of owner decisions:

- Every edit needs a **version increment** (the compiler enforces it).
- A value marked `status: approved` needs `approved_by` and `approved_on`.
- After a change, re-run `trader profile activate` for paper or live. A running session halts
  on a mid-session configuration change by design.

## Commit messages

Imperative subject line (under ~72 characters), blank line, then what changed and why.
Reference decision IDs (`UD-nn`, `ADR-0nn`, `BL-0nn`) where relevant.
