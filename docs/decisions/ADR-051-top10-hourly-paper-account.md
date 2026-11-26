# ADR-051: A ten-coin hourly paper account ("top10"), exact borrow accrual, paced candle requests

- **Status:** Accepted (2026-11-26; owner decision UD-33 in the project thread "Improve bot
  performance from trade data")
- **Context:** The owner was unhappy with the paper bots and asked for "more frequent trades
  on more of the top cryptos" to gather data faster. EXP-2026-023 showed that the three
  leveraged accounts are one bet at three sizes (the same three coins, all on the same side
  about two thirds of the time) and make about 26 entries a month between them.
  EXP-2026-024 replayed the same trend rule on the twenty largest coins with small positions
  and a wider stop: more separate decisions, a smaller drop, and it held on coins and years
  the rule had never seen. Asked "Start a top-20 paper bot beside the existing ones, at which
  speed?", the owner chose **"Hourly decisions only"** (02:11 UTC), which approved the values
  of the write-up, and then wrote **"correct from top 20 to top 10"** (02:13 UTC).
  Four things stood in the way:
  1. A perps settings file could only name SOL, ETH and BTC, each with a Solana token mint,
     because the engine was written for Jupiter Perps.
  2. Borrow was rounded to a whole cent at every accrual. An hourly position of about $125
     owes $0.002 an hour, which rounded to nothing: the new account would have paid no
     borrow at all.
  3. Ten coins on two timeframes are twenty candle requests a cycle. Kraken limits public
     candle requests by IP address and pair and asks for about one call a second.
  4. Auto-deploy (ADR-047) reads its service list before it pulls, so a service added by
     the commit being deployed is not started by that deploy.
- **Decision:**
  1. **A venue that is no venue.** `venue: generic_perps` in a perps settings file means a
     paper model of no particular exchange: any coin with a public candle feed, no price
     mint, at the costs the file states. `jupiter_perps` files keep their rules (only SOL,
     ETH, BTC, each with a mint). A repeated market is refused. `mode` is still only
     `paper`.
  2. **The account.** `configs/perps/top10.yaml`, service `perps-top10`, files
     `data/state/perps-top10.json` and `data/logs/perps-top10-*.jsonl`, alerts
     `[perps top10]`. Coins, in decision order: BTC, ETH, BNB, XRP, SOL, TRX, HYPE, ZEC,
     DOGE, LINK (the ten largest on 2026-11-24, stablecoins and wrapped coins left out).
     Values (UD-33): $2,500; 1% of equity posted per position; leverage from a buffer of 8
     typical daily moves, never above 5x; a stop at 30% of the collateral with the 4/8/12R
     ladder closing 25/25/50 (ADR-045); one position a coin, long or short, on the shared
     trend rule (ADR-044); 7 bps a side and 0.0016% an hour, the main account's cost model;
     the 15% bad-day stop. A stopped trade loses about 0.3% of equity, about 3% if all ten
     stop together. The liquidation model (maintenance, venue ceiling) is copied unchanged
     from `jupiter.yaml`.
  3. **Hourly, and only hourly.** The account decides, marks and stops every hour and reads
     its trend and volatility from 4h candles (ADR-040). The command line refuses any other
     timeframe for it (exit 2), and refuses to start an account that names a coin without a
     candle feed (exit 2), instead of failing every cycle.
  4. **Borrow accrues exactly, for every account.** It is accrued to a millionth of a dollar
     and becomes whole cents only when it is paid, at a close or a take-profit. Cash stays
     in whole cents. Saved runs load unchanged; nothing is reset.
  5. **Polite requests.** `trader/perps/candles.py` spaces this account's requests one
     second apart and retries a refused or failed request twice (after 3 s and 8 s) before
     the cycle gives up and the loop tries again a minute later. The account also waits 180
     seconds after a bar closes instead of 90, so its requests do not land in the second in
     which the three-coin accounts ask for BTC, ETH and SOL. The other accounts fetch as
     before.
  6. **A new service starts itself.** `scripts/ops/start_new.sh` runs at the start of every
     watchdog run. When the last auto-deploy built exactly the commit on disk and other
     paper services have containers, it creates any listed paper service that has none. It
     never builds, never touches an existing container (a bot the owner stopped stays
     stopped), does nothing after `docker compose down`, and `live` is not in its list.
  7. The watchdog, the review assistant's account lists and the status push cover the new
     account. The dashboard does not show it yet.
- **Evidence** (replays of past prices at the modelled costs; simulated, not a forecast,
  and profit is not guaranteed or implied; `research/EXP-2026-024-results.txt`):
  - Exactly this account, hourly, on five slices: 4% to 16% a year, largest drop 12% to
    28%, about 115 entries and 40 separate decisions a month. At twice the costs it is
    about zero. The 4h version returned more on both slices of these ten coins; the owner
    chose hourly for the trade count.
  - Borrow, the same account at its real $2,500 balance, 2020-23 / 2024-26: with cent
    rounding it paid fees of 6% / 7% of equity a year and returned 20.2% / 14.3% a year;
    with exact accrual 10% / 11% and 15.9% / 9.4%, which is what the replay at 100 times
    the balance always said (15.9% / 9.3%). The rounding flattered this account by 4 to 5
    points a year.
  - The existing accounts barely move, in either direction (same windows, return a year,
    cent rounding to exact): main 207.15% to 207.19% and 60.97% to 61.02%; degen 79.80% to
    79.92% and 9.89% to 10.44%; spot-perps 82.71% to 82.64% and 14.78% to 14.68%. Largest
    drops and Sharpe are unchanged to the first decimal.
- **Consequences:**
  - Paper only. This account models no venue: Jupiter Perps lists three of its ten coins,
    so it could not go live there. A live version needs a venue that lists these coins,
    that venue's real fees and funding, its own ADR, and the owner's yes. Per the owner
    (2026-11-26) a live version must let the user set the risk values.
  - Known limits of the model: funding payments are not modelled; a stop fills exactly at
    the stop price; candles come from Kraken while the replay used Binance; a coin whose
    Kraken pair is missing an hourly candle makes that hour wait for all ten; a coin listed
    on Kraken for less than about 34 days has too little history for the trend rule and
    stays flat until it has enough.
  - If one pair cannot be fetched, the whole account waits (no marks, no stops) and alerts
    once, like the other accounts. The watchdog reports it as stale after about two and a
    half hours.
  - The phone gets this account's opens, closes and take-profits: about 8 to 10 messages a
    day on top of the other accounts'.
  - The existing accounts' fees now match the configured borrow rate; their saved runs
    continue and no reset is needed.
