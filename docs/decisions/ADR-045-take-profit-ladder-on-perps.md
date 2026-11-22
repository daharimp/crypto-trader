# ADR-045: A take-profit ladder with a stop move after each take-profit (paper perps)

- **Status:** Accepted (2026-11-22; owner decision UD-32)
- **Owner decision UD-32 (2026-11-22):** the owner wants every trade to keep a stop that
  moves to protect gains: "hits 1st TP > move SL, hits 2nd TP > move SL > 3rd TP". Shown
  EXP-2026-022 (`research/EXP-2026-022-results.txt`, past prices, not a forecast), which
  found every ladder earned much less than a fixed stop with the signal exit on all three
  bots, the owner first chose a test on the degen account only, then decided: "keep both SL
  around 20-30% but we need to implement that rule that has the TP points with the SL
  adjustments after each TP". So both paper perps accounts get a 30% stop and the ladder.
- **Decision:**
  1. Perps configs accept an optional ladder in `risk`: `take_profit_1_r`,
     `take_profit_1_close_pct`, `take_profit_2_r`, `take_profit_2_close_pct`,
     `take_profit_3_r`. All five or none; levels positive and increasing; the two close
     shares positive with something left for TP3; a ladder needs the stop, because R is the
     distance from entry to the opening stop (recorded when the position opens). A `TBD`
     ladder value fails closed (exit 3) like any other.
  2. TP1 closes its share of the opening size and moves the stop to breakeven (open and
     close fees covered); TP2 closes its share and moves the stop to TP1; TP3 closes the
     rest. A stop never moves backwards. After TP3, or a stop after a take-profit, the
     market waits for the next UTC day (ADR-038), as after any stop.
  3. Fills follow the replay, pessimistic where the bar's order is unknown: the stop is
     checked first on the bar's adverse extreme (a gap fills at the open), then each
     take-profit on the favorable extreme at its level; if that bar closes past the moved
     stop, the rest exits at the close.
  4. Partial closes are journaled as `TAKE_PROFIT` events (and phone alerts); the trade
     history adds them to the trade's P&L when the rest closes.
  5. **Values (UD-32):** `stop_loss_pct_of_collateral` 30 on both accounts (main tightens
     from 50, UD-31; degen keeps 30, UD-29). About 1.2 typical daily moves from entry on main
     (buffer 4) and 0.9 on degen (buffer 3). Ladder **TP 4/8/12R closing 25/25/50** on both:
     re-checked for these stop widths on each account's entries (2020-2023 in-sample, 2024
     on holdout), it had the best average in-sample return/drawdown of 18 ladders (MAR 2.21
     main, 1.53 degen; the 1/2/3R ladder was 1.03-1.13 and 0.27-0.34). Every ladder still
     trailed the plain 30% stop (holdout: main 12.1%/yr vs 1.9%, degen 12.8%/yr vs 1.5%);
     the owner chose it knowing that. Merging the pull request approves the placement.
  6. Spot is unchanged (its own 2 x ATR stop, UD-16).
- **Consequences:** the paper runs show the ladder live. Both runs are archived
  (`trader perps paper reset --reason`, ADR-041) before the change goes live so the ladder
  runs start clean. Removing the five keys turns the ladder off.
