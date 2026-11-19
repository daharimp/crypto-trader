# 2026-11-19: Merge all changes onto main (owner request)

- [x] Confirm every stacked leverage PR (#20, #21, #23, #24, #26) reached `crypto-trader` (re-landed via #33 and #34)
- [x] Merge `main` into `crypto-trader` on `chore/merge-main`; conflicts keep `crypto-trader`, dependency and CI updates from `main`
- [x] Lint, format, mypy, full test suite: 534 passed
- [ ] Merge this PR into `crypto-trader`
- [ ] Open and merge `crypto-trader` into `main`
- [ ] Owner: on the server, `git pull && docker compose build && docker compose up -d` (stays on branch `crypto-trader`)
