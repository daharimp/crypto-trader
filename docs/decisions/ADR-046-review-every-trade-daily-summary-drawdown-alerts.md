# ADR-046: Review every trade, a daily summary for every account, and drawdown alerts

- **Status:** Accepted (2026-11-22; owner request)
- **Owner request (2026-11-22):** "is the assistant analyzing these trades?" then "yes" to
  making it do so.
- **Context:** The review assistant (ADR-039) only reviews a perps account's bad day
  (`DAY_HALTED`) and only for main and degen. No account has had one, so it has written
  nothing, and it never looks at spot, the spot-perps account (ADR-044) or single trades.
- **Decision:**
  1. **Every closed trade** of every account in `report_accounts` gets one Claude request (role
     `trade_analyst`, effort in `configs/assistant.yaml`): why it opened, why it closed, how the
     stop-loss and any take-profit steps behaved, whether it followed its rules, a grade of the
     decision (not the outcome) and at most three things to look at. Code builds the fact pack:
     the trade as journaled, every event of that market while it was open (stop moves,
     take-profit partials from the ladder work), the account's settings, the candles from 12 bars
     before entry to the exit, and measured excursions (best move for, worst move against, share
     of the best move kept). Reports: `data/reports/trades/<account>/<close>-<market>-<side>.md`
     plus `.json`; a one-line `[review]` alert per trade.
  2. Perps trades pair `OPENED` with the next `CLOSED`/`LIQUIDATED` of the same market
     (`trader.perps.trade_log`, in the perps package because a perps trade carries leverage).
     Spot trades come from the spot ledger's closed round trips, which do not record why a
     trade closed; the analyst is told so and must label any guess.
  3. **Daily summary** after 00:10 UTC for the previous UTC day: a code-built table per account
     (equity, closed P&L, trades and wins, drawdown from peak, open positions), then one Claude
     request (`daily_editor`) that also reads that day's trade analyses. Report:
     `data/reports/daily-<day>.md`.
  4. **Drawdown alerts** are code only: when an account's equity falls past a level in
     `drawdown_alert_pct` (default 5, 10, 15 % from its peak) one alert is sent per level; the
     memory resets once the account recovers above the lowest level. They never change trading.
  5. Bad-day reviews (ADR-039) also cover spot-perps.
  6. First start: only trades closed in the last 24 hours are analyzed, so switching this on does
     not bill an analysis of every historical trade at once. `trader review trade --account X
     --last N` analyzes older ones on demand.
  7. Nothing changes the authority model: the assistant writes only `data/reports/` and its
     cursor `data/state/review-assistant.json`, never a config or an order.
- **Consequences:** API cost grows with trade count (one request per trade at medium effort, one
  per day). Older `assistant.yaml` files still load with the new features off. The spot exit
  reason is unknown until the spot ledger records it (possible follow-up).
