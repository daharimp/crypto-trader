### Added
- `trader perps paper reset --reason` archives a paper perps run (state, trades, per-bar equity curve and a `summary.json`) instead of wiping it; `trader perps paper runs` lists past runs, including older hand-moved state files (ADR-041).
- Paper perps sessions record one equity point per processed bar in `data/logs/<stem>-equity.jsonl`.

### Changed
- A running paper perps session whose run was archived under it alerts and exits instead of writing the old run back.
