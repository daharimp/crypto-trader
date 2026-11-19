# ADR-040: Hourly sweep with the 30-day trend read from 4-hour candles

- **Status:** Accepted (2026-11-16; owner request)
- **Owner request (2026-11-16):** "it should sweep more often for trades"; after seeing the
  replay (`research/sweep-frequency-replay-results.txt`): "make the requested changes".
- **Context:** The paper perps session decides once per completed 4h candle. A 1h session
  existed (`--timeframe 1h`) but could never trade on Kraken's free feed: it returns 720
  candles including the forming one, while a 30-day trend and the 30-day volatility on 1h
  candles need 721 completed ones. The replay found hourly decisions about even with
  4-hourly ones (twice the trades and fees, fewer liquidations, slightly better recent weeks).
- **Decision:**
  1. New optional session setting `trend_timeframe`. With `--timeframe 1h` the CLI sets it to
     `4h`: every completed hour the account marks positions (liquidation and stop checks),
     reads the signal from completed 4h closes plus the latest hourly close, takes the
     volatility from completed 4h closes, and moves toward the signal at the next price. The
     "30 days ago" reference is therefore exact to within one 4h candle.
  2. The setting is saved in the account's state; an account cannot resume under a different
     one (exit 2), like a different signal or timeframe.
  3. The degen paper account (ADR-038) runs hourly in Compose. The main account stays on 4h
     during its 7-day test; switching it later is one Compose flag plus a fresh account.
  4. Risk code, limits and settings are unchanged; the signal still only chooses a side.
- **Consequences:** About twice as many trades and fees on the degen account, stops and
  liquidations noticed within the hour instead of within 4 hours, two candle downloads per
  market per hour from Kraken's public API (well within its limits). The replay is past
  prices, not a forecast.
