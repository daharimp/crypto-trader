# ADR-022: Owner risk decisions of 2026-11-01 and their architectural effects

- **Status:** Accepted (owner decision)
- **Date (UTC):** 2026-11-01
- **Context:** The owner resolved UD-01 to UD-13 and UD-15 to UD-21 by accepting the
  recommendations in `docs/spec/product-requirements.md` §10 (full list in §10.2). UD-14 is
  deferred, and UD-20 still needs a venue.
- **Decisions with architectural effect:**
  1. **UD-05 A:** the first paper adapter is the internal deterministic simulator fed by
     public market data. No exchange credentials are introduced, and the adapter allowlist
     stays `{"simulated"}` (T-46).
  2. **UD-19 D:** engaging the kill switch blocks new orders and leaves positions and their
     protective stops unchanged. A separate, explicit **owner flatten command** will submit exit
     intents through the risk engine and execution gate (new backlog item BL-048, needed before
     forward paper sessions). Automation never flattens.
  3. **UD-15 A (upward bound):** sizing never scales above 1x (`upward_enabled: false`,
     `upward_multiplier_max: 1`).
  4. **Configuration versions:** the risk profiles, eligibility rules, and Balanced trading
     profile move to version 2 (PV-04, PV-10, RP-10).
  5. **Tests:** mechanism tests now run against a frozen copy of the all-`TBD` M1 configs
     (`tests/fixtures/configs/`, selected through `TRADER_CONFIGS_DIR`), so approved values
     cannot change what those tests prove. `tests/unit/test_owner_decisions.py` and
     `tests/e2e/test_shipped_configs.py` cover the approved configs.
- **Consequence:** the shipped Balanced profile backtests without an experiment set. Paper
  sessions remain refused until profile activation (BL-028) and forward paper (BL-027) exist.
  `EXP-2026-001` is now historical: against v2 it is rejected because it targets approved
  fields (RP-12).
