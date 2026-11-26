# ADR-054: An optional size range per paper perps account, chosen inside by a confidence score

- **Status:** Accepted (2026-11-26). The setting exists and is **off in every account**; a
  range goes into a settings file only with the owner's choice (open decision UD-35).
- **Context:** The owner wrote that the size of a position "was always a range so not every
  trade needed to be 10% a position, it should be assessed based on confidence" (2026-11-26
  02:23 UTC), and for main chose "Keep 5% to 15% (10% for now)": main stays at a flat 10%
  until a confidence measure passes a backtest. The code only ever had one number per
  account, `max_collateral_per_position_pct`, and every position posted it. An earlier
  score (2026-11-15) did not predict which trades won.
  EXP-2026-026 tested five measures on seven slices (three of them coins or years the rule
  had never seen) under a rule written beforehand. One passed, narrowly: **the composite**,
  the plain average of breadth, trend strength and timeframe agreement. Sized by it inside
  a range of half to one and a half times the flat size, the account's Sharpe ratio was
  higher than a flat twin of the same average size on five of seven slices and two of the
  three unseen ones. The results file lists four cautions, and they shape this decision:
  six of the seven intervals include zero; a check that does not depend on the size fails;
  the score does not pick winners more often, it picks bigger winners; and it concentrates
  risk (the deepest drop is deeper on all seven slices, the worst day worse on six). The
  evidence is firmer on the ten-coin hourly account than on main. All of it is a simulation
  of past prices, not a forecast.
- **Decision:**
  1. **One optional risk key**, `risk.min_collateral_per_position_pct`, in a perps settings
     file. Absent: every position posts `max_collateral_per_position_pct`, exactly as
     before. Present: the two keys are the owner's range, smallest and largest collateral
     per position as % of equity. `TBD`: the account does not start (exit 3). A value must
     be above 0 and not above the maximum (exit 2 otherwise).
  2. **The size rule lives in the risk code** (`trader.perps.risk.collateral_pct`):
     size = smallest + (largest - smallest) x score, in steps of 0.0001 points. A score
     outside 0 to 1 is clamped, so no input can push a size outside the owner's range. The
     signal still only says long, short or flat; it never sizes. Every other limit (total
     size, leverage ceiling, liquidation distance, stop, daily loss limit) is applied to
     the sized position afterwards, unchanged.
  3. **The score is deterministic** (`trader.perps.confidence`): no model, no network. It
     is the composite that passed, from candles that had closed at the decision:
     the share of the account's other markets whose signal is on the same side; where the
     market's efficiency ratio stands among its values at the previous 540 4h closes; and
     whether the 4h 50/200 averages and the daily close against its 200-day average agree
     with the side. A reading without enough history counts as 0.5, as in the experiment.
  4. **No score, no trade.** With a range set, an open that arrives without a score is
     refused with `PERP_CONFIDENCE_UNAVAILABLE`. A missing score never falls back to a
     default size.
  5. **Smallest equal to largest is allowed.** The size is then fixed and the score is only
     recorded, which lets an account collect scores on paper before anything is sized by
     them.
  6. **The session reads two more views when a range is set**: 4h candles (already read by
     an hourly account for its trend) and daily candles, one more request per market per
     cycle. It reads every market's signal before any position moves, so one market's score
     can count how the others stand, and it scores only markets about to open.
  7. **Journaled.** With a range set, each `OPENED` event carries `confidence` and
     `collateral_pct`. Without one, the event is unchanged.
  8. Saving and loading the account moves to `trader/perps/account_state.py` to keep the
     session module under the 500-line limit. Nothing else about it changes.
- **Verification:** With the key absent, a full replay with sized entries is identical to
  the one made before the change (`run_exp026.py step2-A1`, every number). With it set, the
  account takes exactly the trades and sizes of the research composite on a 4h slice and an
  hourly ten-coin slice (`run_exp026.py engine-A3`: 1,859 events; `engine-B4`: 4,637 events;
  both identical). The exchange hands the bot 720 candles where the experiment had the whole
  history; read from that shorter window the largest difference in a score is 0.0012. A
  30-day dry run of the real bot loop with a range set matches the research replay (results
  file, "The built setting"). Unit tests: `tests/unit/test_perps_confidence.py`.
- **Consequences:** No account changes behaviour with this change. Switching a range on is
  a settings change with the owner's approval fields, a raised `version` and a restart; it
  needs no reset, because the saved run loads as it is and open positions keep their size.
  Raising an account's largest size is a change to a risk value and needs the owner's yes
  like any other. With a range on, the largest positions are larger than the flat size, so
  the worst days are worse by the amounts in the results file. The average size sits a
  little under the middle of the range, because scores average a little under one half (in
  the replays 9.7% to 9.8% inside 5% to 15%, and 0.93% to 0.95% inside 0.5% to 1.5%). Main
  keeps its flat 10% until the owner decides otherwise.
- **Alternatives considered:** A score from a language model (not deterministic, and a
  model's answer would then size a position). Letting the signal return a size (strategies
  never size). Sizing by breadth or by timeframe agreement alone (neither passed the rule).
  A default size when the score is missing (an invented value; refusing is the fail-closed
  choice). Three fixed tiers instead of a line (not what was tested). Switching the range
  on for the ten-coin account in this change (the range is a risk value; the owner chooses).
