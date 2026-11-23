# 2026-11-23: Free OpenRouter model reviews each trade (owner request)

- [x] `free_trade_reviews` settings, reviewer, validation + one retry, daily budget (ADR-049)
- [x] Reports with raw facts in `data/reports/trades/` for the daily Claude review
- [ ] Owner: add `OPENROUTER_API_KEY` to `.env`, allow free endpoints in OpenRouter privacy settings
- [ ] Scheduled daily review reads `reports/trades/` notes and facts in crypto-trader-ops
