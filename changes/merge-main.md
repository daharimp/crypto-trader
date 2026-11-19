### Changed
- `main` is merged into `crypto-trader`, so the two branches share history and
  `crypto-trader` can then go to `main` without conflicts. Every conflicting file keeps the
  `crypto-trader` version (including `configs/live/authorization.yaml` v3, live still off,
  and `CLAUDE.md`); from `main` it takes only the dependency updates (ccxt 4.5.92, pandas
  3.1.1, pyarrow 26.0.1, pydantic 2.14.3, typer 0.29.1, ruff 0.17.4, hypothesis 6.170.15,
  types-pyyaml) and CI's `actions/checkout@v7` and `actions/setup-python@v7`.
