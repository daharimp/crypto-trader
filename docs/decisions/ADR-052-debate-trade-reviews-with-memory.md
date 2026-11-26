# ADR-052: Debate-style free trade reviews with a memory of past calls

- **Status:** Accepted (2026-11-26; owner approved "have two free AI models argue for and
  against each trade, and let reviews learn from how past calls turned out" in the project
  thread, after the open-source survey)
- **Context:** ADR-049 gives each closed paper trade one review from a free OpenRouter model.
  One model's answer anchors on itself (the first free review called a trend-following short
  "counter-trend"). TradingAgents (Apache-2.0) gets better reviews from a bull/bear debate
  and a decision log that is later compared with what really happened. The free account
  allows 50 requests a day, failed ones included.
- **Decision:**
  1. New `free_trade_reviews` keys (all off by default for older files): `debate`,
     `bull_models`, `bear_models`, `judge_models` (each falls back to `models`),
     `memory_reviews` (5) and `follow_up_bars` (6). Shipped: debate on, the bull starts on
     Nemotron 3 Ultra and the bear on Gemma 4 31B so the two sides are different models;
     the judge starts on Nemotron. `lookback_hours` goes from 24 to 48 so trades the day's
     budget cannot reach wait for the next day's.
  2. Per trade: bull and bear each write a free-text case (no format to break, no retry),
     then the judge returns `DebateVerdict` (the ADR-049 `TradeAnalysis` plus 1-5 process
     scores for entry, stop placement, exit management and rule adherence, the bull and
     bear points that held, a `stop_call`, an `exit_call` and a one-sentence lesson), checked
     by code with one retry. Every role is told to grade how the trade was run, not its
     profit; code sets the outcome quadrant ("sound process, bad luck", "poor process,
     lucky", ...) from the grade and the P&L.
  3. Budget: a debate costs up to 4 requests (3 + the judge's retry). A trade gets a debate
     only while the rest of the budget can still give every other due trade a 2-request
     single review; otherwise it gets the ADR-049 single review; when even that does not fit
     it waits for tomorrow. The cap stays 45 a day. With the $10 one-time OpenRouter credit
     (1,000 a day) every trade would get a debate; that is the owner's call.
  4. Memory: each verdict is saved to `data/reports/trades/memory.json` (newest 300). Once
     `follow_up_bars` candles have closed after the exit, code measures the price move in the
     trade's direction and marks the stop and exit calls right, wrong or unclear (a move
     under 1% is unclear). The judge then sees its last 5 verdicts on that account with those
     marks and a scorecard, and is told to discount the calls it often gets wrong.
  5. `data/reports/trades/lessons.md` (per-account scorecard plus the newest lessons with
     their checks) is pushed to the ops repo with the trade notes for the daily Claude review.
- **Consequences:** about 3 requests per trade instead of 1, so roughly 11 trades a day get a
  debate before the rationing falls back to single reviews. Reviews remain advice only:
  nothing here edits a setting or places an order. The follow-up check uses public Kraken
  candles; a trade older than the fetcher's window is marked "no longer available" after
  three days. The 1% threshold and 6 bars are review settings, not risk values.
