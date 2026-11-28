# ADR-057: A failed debate falls back to a single free review, and errors keep their reason

- **Status:** Accepted (2026-11-28, daily scheduled review; a reliability fix to the review
  assistant, no trading or risk value changes)
- **Context:** The first debate review (ADR-052) ran on 2026-11-27 for the top10 DOGE stop-out
  and produced nothing. The bull got an empty answer, the bear got an error object with no
  `choices` (logged only as `KeyError: 'choices'`), and both judge attempts got
  `HTTP Error 400: Bad Request` with the response body thrown away. The trade was marked done
  and never retried, so it has no review at all. Before debates, single reviews worked on all
  9 trades (2026-11-23). The cause cannot be pinned from the ops repo because the error text
  was lost.
- **Decision:**
  1. When a debate gives no verdict and the day's budget still holds a single review on top of
     the room kept for the other due trades (the ADR-052 rationing rule), the trade gets the
     ADR-049 single review in the same pass. The debate's arguments stay in the report. A
     single review is not a verdict, so nothing goes into the outcome memory.
  2. An HTTP error keeps its status and the first 300 characters of the provider's error body
     (`HTTP 400: {...}`). An error object with no `choices` keeps its `error` message. The
     request carries the key only in a header, which error bodies do not echo.
- **Consequences:** a failed debate can cost up to 6 requests instead of 4. The budget check
  still prevents it from going over the daily cap or using the share kept for other trades. The
  next failure will show why it failed in the trade note. Reviews remain advice only: nothing
  here edits a setting or places an order.
