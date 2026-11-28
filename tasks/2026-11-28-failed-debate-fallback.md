# 2026-11-28: Free review fallback when a debate fails (found in the daily review of 2026-11-27)

The top10 DOGE stop-out on 2026-11-27 got no review: all four debate requests failed, and the
reasons were cut to `KeyError: 'choices'` and `HTTP Error 400: Bad Request` (ADR-057).

- [x] A failed debate falls back to a single review when the budget allows it
- [x] HTTP errors keep their status and error body; error objects keep their message
- [x] Tests: fallback succeeds, the fallback is skipped when the budget is spent, both fail
      (reasons joined), error object, HTTP body with and without a body
- [x] ADR-057, RUNBOOK note, change note
