# ADR-049: Per-trade reviews on a free OpenRouter model; Claude keeps the daily review

- **Status:** Accepted (2026-11-23; owner asked for "the free model on each trade, then Claude
  Opus for the daily review" in the project thread)
- **Context:** ADR-048 turned the server's Anthropic calls off; the daily scheduled review on
  the owner's Claude plan writes the daily summary. The owner wants each trade reviewed soon
  after it closes without paying per call. The server (1 GB, 1 vCPU) cannot run a useful
  local model, so a free hosted model is used. OpenRouter serves free open models through
  an OpenAI-style API at 20 requests/min and 50/day (1,000/day after a one-time $10 credit
  purchase); failed requests count. The free list changes often, and each free model has a
  single provider.
- **Decision:**
  1. New `free_trade_reviews` block in `configs/assistant.yaml` (off by default for older
     files; shipped on). It lists up to three models, sent as OpenRouter's `models` list so a
     busy model falls back to the next. Shipped: `nvidia/nemotron-3-ultra-550b-a55b:free`,
     then `google/gemma-4-31b-it:free`. Model names live only in this file.
  2. The key is read only from `OPENROUTER_API_KEY` in the server's `.env`. Without it, or
     with the block disabled, nothing runs and nothing alerts.
  3. `review watch` reviews each paper trade closed in the last `lookback_hours` (24) once,
     using the existing `trade_analyst` role and `TradeAnalysis` schema. Code validates
     every answer, asks once more with the error (`retries: 1`), and otherwise saves the facts
     with "review skipped" instead of failing.
  4. A daily call budget (`daily_call_budget: 45`, retries reserved) keeps the account under
     the free cap. Trades beyond it wait for the next UTC day while still in the lookback.
  5. Reports go to `data/reports/trades/<account>/` (Markdown plus JSON with the raw facts
     and the model that answered), which the hourly status push copies to the ops repo. The
     daily Claude review reads both the notes and the raw facts, so a weak free answer cannot
     decide the daily verdict.
- **Consequences:** Per-trade reviews cost nothing; quality is below Claude's and free models
  may disappear, so the model list needs occasional edits. Free providers may log or train on
  prompts; the prompts hold only simulated trade numbers and settings, no keys. Before any
  live-money review, switch to a paid or no-training model. The OpenRouter account's privacy
  settings must allow free endpoints that may train on inputs, or requests are refused.
