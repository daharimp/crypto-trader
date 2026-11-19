# ADR-034: Research replay for opening-leverage policies

- **Status:** Accepted (2026-11-12; research tooling only)
- **Context:** The owner asked whether volatility-assessed opening leverage (ADR-032, UD-26,
  UD-27) beats fixed 12x and whether leverage should also rise on a strong signal. The lab
  (ADR-027) only models positions at 1x without liquidation, and the paper simulator has no
  measured funding and compounds one shared account.
- **Decision:**
  1. `trader.perps.leverage_replay` replays one market on constant capital: fixed collateral
     per trade, leverage fixed at the open, fees on size, measured funding (ADR-033) or a
     borrow fee, liquidation against each bar's adverse extreme with the whole collateral
     lost. It mirrors the simulator's rules in floats; a unit test checks one trade against
     `PaperPerpsAccount` to the cent.
  2. It lives in `trader/perps/` because T-46 allows this vocabulary only in the paper-only
     perps package. It is imported only by `research/run_exp015.py` and its tests, never by
     the session, the simulator, or the trading pipeline.
  3. Leverage formulas restate ADR-032 (`1 / (buffer x daily move + fee + maintenance)`,
     rounded down to 0.1, between 1x and the ceiling). Buffer steps and strength thresholds
     are experiment inputs fixed in `research/EXP-2026-015-plan.md`, not configuration.
- **Reason:** answer a sizing question with measured costs without touching approved values.
- **Consequence:** no config, risk value, or session behaviour changes. Account-level limits,
  compounding, and running out of money are not modelled, so results are per-coin comparisons
  of policies, not forecasts of the paper account.
- **References:** ADR-025, ADR-027, ADR-031, ADR-032, ADR-033, UD-23, UD-25, UD-26, UD-27,
  EXP-2026-014, EXP-2026-015.
