# ADR-031: Forward paper perps session (long and short on live prices)

- **Status:** Accepted (2026-11-12; owner decision UD-24)
- **Owner decision UD-24 (Dahari Morgan-Parker, 2026-11-12):** "this bot should focus on
  margin and perps"; the spot bot "is still only trading on uptrend" and the bot should ride
  downtrends too; the paper practice session is approved to run. Real-money margin or perps
  is **not** part of this decision.
- **Context:** The only session on the server was the spot bot. Spot cannot profit from a
  falling price, so in a downtrend it sits in cash. The perps package (ADR-025) could replay
  history but had no forward session, so the two-sided behaviour the owner wants never ran.
- **Decision:**
  1. `trader perps paper run` runs a forward paper account on public candles. Each cycle
     processes every newly completed bar in the replay's order: mark open positions against
     the bar's adverse extreme (liquidation), accrue the hourly borrow fee and roll the day;
     read the signal from closes up to that bar; move toward the signal at the next bar's
     open (for the newest bar, the latest traded price).
  2. The signal is injectable (`closes -> long | short | flat`). The default is the replay's
     `sma_stance` 20/50, so forward results can be compared with history. Better two-sided
     signals arrive as separate changes with their evidence.
  3. Sizing and every limit come from the existing owner-approved values (UD-23, config v5)
     through the unchanged `size_open`/`check_open`. Unapproved values still exit 3.
  4. State is saved atomically after each cycle (`data/state/perps-paper.json`) and events
     are appended to `data/logs/perps-paper-events.jsonl`; a restart resumes the same
     account, and a state file from a different signal, timeframe, or market list is refused.
  5. The persisted kill switch blocks new paper positions. Opens, closes, and liquidations
     go to the owner's alert channel in plain language.
  6. `docker compose up -d perps` runs it beside the spot `paper` service.
- **Unchanged:** paper only (`mode` is `Literal["paper"]`); no wallet key, no signing, no
  transaction, no order to any venue. Spot stays long-only with no leverage. Real-money
  margin or perps needs its own ADR, gates, and a venue the owner may legally use.
- **Consequences:** Prices are Kraken spot candles standing in for Jupiter's oracle price.
  Liquidation is checked once per completed bar against its high or low, and loses the whole
  collateral (conservative). The borrow fee is the owner's cautious 0.01%/h. In the replay
  this signal lost money at 10x (TASK.md, 2026-11-10), so paper losses are expected until a
  better signal is added; the session exists to measure that on new data.
