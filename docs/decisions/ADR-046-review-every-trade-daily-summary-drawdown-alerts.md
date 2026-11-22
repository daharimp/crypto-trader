# ADR-046: Review every trade, a daily summary for every account, and drawdown alerts

- **Status:** Accepted (2026-11-22; owner request)
- **Owner request (2026-11-22):** "is the assistant analyzing these trades?" then "yes" to
  making it do so.
- **Context:** The review assistant (ADR-039) only reviews a perps account's bad day
  (`DAY_HALTED`) and only for main and degen. No account has had one, so it has written
  nothing, and it never looks at spot, the spot-perps account (ADR-044) or single trades.
- **Decision:**
  1. **Every closed trade** of every account in `report_accounts` is reviewed once a day, in
     the same single Claude request as the daily summary (owner, 2026-11-22: "review each trade
     eod and give a daily summary if that saves usage"). For each trade: why it opened, why it
     closed, how the stop-loss and any take-profit steps behaved, whether it followed its rules,
     a grade of the decision (not the outcome) and at most two things to look at. Code builds
     each trade's facts: the trade as journaled (ladder `TAKE_PROFIT` partials count toward its
     P&L), every event of that market while it was open, the last 30 candles up to the exit, and
     measured excursions (best move for, worst move against, share of the best move kept). At
     most 40 trades per day are reviewed so a request stays bounded. `trader review trade`
     reviews chosen trades on demand, one request each.
  2. Perps trades pair `OPENED` with the next `CLOSED`/`LIQUIDATED` of the same market
     (`trader.perps.trade_log`, in the perps package because a perps trade carries leverage).
     Spot trades come from the spot ledger's closed round trips, which do not record why a
     trade closed; the analyst is told so and must label any guess.
  3. **Daily summary** after 00:10 UTC for the previous UTC day: a code-built table per account
     (equity, closed P&L, trades and wins, drawdown from peak, open positions), then the
     `daily_editor` narrative and the trade reviews, rendered under the measured line of each
     trade. Report: `data/reports/daily-<day>.md` plus `.json`; one `[review]` alert.
  4. **Drawdown alerts** are code only: when an account's equity falls past a level in
     `drawdown_alert_pct` (default 5, 10, 15 % from its peak) one alert is sent per level; the
     memory resets once the account recovers above the lowest level. They never change trading.
  5. Bad-day reviews (ADR-039) also cover spot-perps.
  6. Nothing changes the authority model: the assistant writes only `data/reports/` and its
     cursor `data/state/review-assistant.json`, never a config or an order.
- **Consequences:** One request per day whatever the trade count (plus bad-day reviews); a busy
  day makes that request larger, capped at 40 trades. Older `assistant.yaml` files still load with the new features off. The spot exit
  reason is unknown until the spot ledger records it (possible follow-up).
