# ADR-016: Unresolved values fail closed; experiment parameter sets only in research backtests

- **Status:** Proposed (R-02)
- **Decision:** Every risk value carries a provenance status (`approved`, `hypothesis`, `unresolved`). A required `TBD` value blocks the run (exit code 3) with its UD ID. In backtests only, an experiment parameter set may supply values for `unresolved` or `hypothesis` fields; such values are labelled `experiment` in the `CompiledProfile`, the journal, and every report. Experiment values are refused in the `paper` environment and can never change approved values or safety constants.
- **Reason:** Lets the M1 slice run end to end and lets experiments produce evidence for UD decisions, without inventing profile values.

Source: `docs/spec/architecture.md` §14.
