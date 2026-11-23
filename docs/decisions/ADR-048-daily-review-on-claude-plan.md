# ADR-048: Daily summary and trade reviews move to the scheduled review; server AI off

- **Status:** Accepted (2026-11-23; owner chose "let the daily scheduled review do it" in the
  project thread)
- **Context:** ADR-046 had the `review` service call the Anthropic API from the server once a
  day for the daily summary and per-trade reviews, plus bad-day reviews (ADR-039). The API
  account has no credits, so those calls fail. ADR-047 already gives a daily scheduled
  review, running on the owner's Claude plan, that reads the same reports, state and event
  logs from the private `crypto-trader-ops` repo.
- **Decision:**
  1. New assistant setting `server_ai_reviews` (default `true`, so older files are unchanged).
     `configs/assistant.yaml` sets it to `false`: `review watch` then makes no API request
     (no bad-day reviews, no daily summary or trade reviews) and no longer needs
     `ANTHROPIC_API_KEY`. The code-only drawdown alerts at 5/10/15 % keep running.
  2. The daily scheduled review writes the summary of all four accounts and a review of each
     trade closed that UTC day to `reviews/daily-<day>.md` in `crypto-trader-ops`, and sends
     a push notification with the headline. It can only write reports and open pull requests;
     strategy and risk changes still go through tested pull requests.
  3. `push_status.sh` rebases on the ops repo before pushing so those review commits and the
     server's hourly status commits never collide (the server never writes `reviews/`).
- **Consequences:** no API spend on the server. Reviews depend on the hourly status push; if
  it stops, the 4-hourly check reports the server as quiet. Setting `server_ai_reviews: true`
  (with a funded key) restores the server reviews. An open-source model replacement is being
  researched separately.
