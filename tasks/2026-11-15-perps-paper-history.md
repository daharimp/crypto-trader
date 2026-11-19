# 2026-11-15: Paper perps history for the dashboard redesign (owner request)

First step of the Trader Desk redesign: the data the new screens need. No page change yet.

- [x] `trader.perps.history`: closed trades, recorded equity points and open-position
      details rebuilt from the event log (read-only)
- [x] `/api/perps-paper` carries `trades`, `equity`, and `leverage`, `liquidation_price`,
      `opened_at` per open position
- [x] Tests: paired trades, liquidation, missing log, torn line, unmatched close, unmatched
      open position
- [x] Next pull request: the swipe dashboard that shows this data (`tasks/2026-11-15-ui-swipe-desk.md`)
