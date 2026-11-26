# ADR-053: An optional cooldown after a losing trade, per paper perps account

- **Status:** Accepted (2026-11-26). The setting exists and is **off in every account**; a
  length goes into a settings file only with the owner's choice (open decision UD-34).
- **Context:** Asked which add-ons to put into the bots, the owner wrote "yes add these bot
  improvements" (2026-11-26 02:16 UTC): a pause after stop-outs with a cooldown after each
  loss, volatility sizing that shrinks when coins move together, and a time limit on trades
  going nowhere. EXP-2026-025 tested all of them on the ten-coin hourly account under a
  rule written beforehand, on four slices (two of them coins or years the rule had never
  seen). Only one passed: **a cooldown after a losing trade**, at 4, 12 and 24 hours. The
  stop guard changed nothing, correlation sizing had no reliable effect, and the time limit
  hurt on three of four slices; none of those is built.
  Why the cooldown helps (exploratory): the hourly account re-reads an unfinished 4h candle
  every hour, so a signal can flip out and back within hours. About 63% of its entries open
  within 4 hours of a losing exit on the same coin, in chains of quick in-and-out trades
  that end with the one entry that catches the move. The cooldown waits out the chain. The
  price is fewer trades: 26% fewer entries at 4 hours, 38% at 12, 46% at 24 (separate
  decisions fall 8%, 13% and 19%). The owner asked for more trades, so the length is the
  owner's to choose and nothing is switched on here.
- **Decision:**
  1. **One optional risk key**, `risk.cooldown_after_loss_hours`, in a perps settings file.
     Absent: no cooldown, and the account behaves exactly as before. `TBD`: the account
     does not start (exit 3), like every unresolved value. A value must be above 0 and at
     most 168 hours (exit 2 otherwise).
  2. **What it does.** When a trade closes with a loss after all fees (opening fee, every
     take-profit, closing fee and borrow; a liquidation always counts), that market opens
     nothing for that many hours. Other markets trade on. A trade that ends exactly even
     starts no wait. The ADR-038 rule (a stopped market waits for the next UTC day) still
     applies on top; the cooldown also covers the case it misses, a stop late in the day
     that reopened just after midnight.
  3. **Counted from the candle, not from the fill.** The live session fills the newest
     decision a few minutes after its candle closes. A wait counted from the fill would end
     minutes after the decision it was meant to allow and cost one more bar, by an amount
     that depends on how late a cycle ran. `apply_signal` and `close` take the decision
     candle's close time for this; the journal keeps the fill's time.
  4. **Kept by the account.** Each position carries what its trade has realized so far
     (`realized_usd`), and the account keeps `cooldown_until` per market; both are saved in
     the state file. State written before this ADR loads unchanged (a position already open
     starts from zero, so its opening fee is not counted). A wait started while the setting
     was on is dropped when the account restarts with the setting off.
  5. **Journaled, not alerted.** The start of a wait is one `COOLDOWN_STARTED` event with
     the time it ends. It is not a phone alert, and the hourly decisions it refuses are
     silent.
  6. **Unknown risk keys are refused** (exit 2). Before this, a misspelled optional key was
     ignored, which would have switched a protection off without a word.
  7. `PerpPosition` moves to `trader/perps/position.py` to keep the account module under
     the 500-line limit. Nothing else about it changes.
- **Verification:** With the setting absent, a full replay with sized entries is identical
  to the one made before the change (`run_exp026.py step2-A1`, every number). With it set,
  the account takes exactly the trades of the research cooldown on all four slices at 4, 12
  and 24 hours: 2,760 to 16,601 events each, identical (`run_exp025.py engine-S1` to
  `engine-S4`). Unit tests: `tests/unit/test_perps_cooldown.py`.
- **Consequences:** No account changes behaviour with this change. Switching the cooldown
  on is a one-line settings change with the owner's approval fields, a raised `version` and
  a restart; it needs no reset, because the saved run loads as it is. Fewer trades while it
  is on, by the amounts above. The stop guard, correlation sizing and the time limit are
  not built; EXP-2026-025 says why.
- **Alternatives considered:** Counting the wait in wall time (simpler, but differs from
  the replays by a bar whenever a cycle runs late). Starting the wait only after a
  stop-loss (most losing exits of the hourly account are signal changes, not stops, so it
  would miss the chains). Keeping the cooldown in the session instead of the account (the
  replays and the backtest command drive the account directly and would not see it).
  Building all four add-ons behind switches (three of them failed their test; a switch
  nobody should turn on is a hazard).
