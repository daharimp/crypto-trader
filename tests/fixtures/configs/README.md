# Test fixture configuration (M1 baseline)

A frozen copy of `configs/` as it was before the owner resolved any decision: every
owner-decision value is `TBD`. Tests use this tree (via `TRADER_CONFIGS_DIR`) so that they
exercise the fail-closed and experiment-overlay mechanisms independently of the values the
owner approves in the shipped `configs/` (handoff §9.1: risk tests use fixtures and never edit
`configs/risk/*.yaml`). Do not edit these files to make a test pass.
