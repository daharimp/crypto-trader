### Added
- Per-trade reviews on a free OpenRouter model (ADR-049): `review watch` reviews each paper
  trade soon after it closes (`free_trade_reviews` in `configs/assistant.yaml`, key from
  `OPENROUTER_API_KEY`), validates the answer, retries once, and saves "review skipped" with
  the facts on failure. The daily Claude review reads these notes and the raw facts.
