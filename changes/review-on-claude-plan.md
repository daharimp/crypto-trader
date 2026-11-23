### Changed
- The server's review assistant makes no AI calls now (`server_ai_reviews: false`, ADR-048):
  it keeps the 5/10/15 % drawdown alerts and no longer needs an API key. The daily scheduled
  review writes the daily summary and trade reviews to the `crypto-trader-ops` repo instead.
