# ADR-055: The dashboard shows the ten-coin paper account, priced from Kraken

- **Status:** Accepted (2026-11-26; owner request, relayed in the project thread, after the
  ten-coin paper account of ADR-051 started)
- **Context:** The dashboard (ADR-026, ADR-037) showed the main and degen paper accounts and
  spot. Its live prices came from the watchlist (BTC, ETH, SOL, XRP, SUI), so the ten-coin
  account (`perps-top10`: BTC, ETH, BNB, XRP, SOL, TRX, HYPE, ZEC, DOGE, LINK) was not
  shown, and BNB, TRX, HYPE, ZEC, DOGE and LINK had no price for gain/loss.
- **Decision:**
  1. `GET /api/perps-top10` returns the account summary, history and settings, read from
     the same files as the other accounts (`data/state/perps-top10.json`, its event log,
     `configs/perps/top10.yaml`). A "Top 10 · paper" button selects it; "All" includes it.
  2. `GET /api/top10-prices` returns `{coin: price}` for the markets in `top10.yaml`: the
     close of the still-forming 4h public Kraken candle, the pairs the bot itself uses. It
     goes through the dashboard's candle cache (ADR-050): one fetch per coin a minute,
     shared with the watchlist, and the last good price when Kraken fails. A coin with no
     known Kraken pair is never requested; a coin whose data fails is left out.
  3. The page keeps the last prices it received if a refresh fails.
- **Consequences:** The dashboard makes up to six more public Kraken requests a minute while
  someone has it open. Read-only, paper only; no bot service or trading setting changes.
