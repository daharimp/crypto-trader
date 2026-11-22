# ADR-043: A take-profit ladder on the degen paper perps account (a live paper test)

- **Status:** Accepted (2026-11-22; owner decision UD-32)
- **Owner decision UD-32 (2026-11-22):** the owner wants every trade to keep a stop that
  moves to protect gains: "hits 1st TP > move SL, hits 2nd TP > move SL > 3rd TP".
  EXP-2026-018 (`research/EXP-2026-018-results.txt`, past prices, not a forecast) found
  that on all three bots every ladder variant earned much less than a fixed stop with the
  signal exit, because the few very large trend trades make most of the profit and a TP3
  cap ends them. Shown that, the owner chose to run the ladder **on the degen account only**
  as a paper test next to the main account's fixed stop.
- **Decision:**
  1. Perps configs accept an optional ladder in `risk`: `take_profit_1_r`,
     `take_profit_1_close_pct`, `take_profit_2_r`, `take_profit_2_close_pct`,
     `take_profit_3_r`. All five or none; levels positive and increasing; the two close
     shares positive with something left for TP3; a ladder needs the stop (R is the
     distance from entry to the opening stop, recorded when the position opens). A `TBD`
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
  5. Main and spot keep their fixed stops; no ladder keys in `jupiter.yaml`.
- **Consequences:** degen's results become a live comparison with main. Before the change
  goes live the degen run is archived (`trader perps paper reset --reason`, ADR-041) so the
  ladder run starts clean. If the ladder underperforms, removing the five keys turns it off.
