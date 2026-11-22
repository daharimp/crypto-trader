# ADR-044: One shared trend rule (50/200, 10/30 in ranges) picks long or short for every bot; spot's rule also runs both ways on 1x paper perps

- **Status:** Accepted (2026-11-22; owner decisions UD-32). Builds on ADR-043 (spot
  `sma_stance` 50/200).
- **Owner decisions UD-32 (2026-11-22):** "The bot should trade in an uptrend or a
  downtrend. It needs to be adaptable ... let's make that universal." After the audit and
  EXP-2026-020 the owner chose "50/200 both ways, every bot", then asked for spot's rule to
  go "short and long", and approved the 1x account's values: $2,500, 15% of equity per
  position, a stop at 6% of collateral (a 6% move at 1x), at most 100% of equity open, and a
  5% bad-day stop. EXP-2026-021 then tested other lengths and range switches; the owner
  chose "50/200 + fast 10/30 in ranges", adding that paper testing can take a lot more risk.
- **Context:**
  - Perps main and degen already traded both ways (`tsmom_30d`, always in the market). They
    held shorts Nov 15-22 because the 30-day trend pointed down on BTC, ETH and SOL all month.
  - Spot is long-only by the safety rules (CLAUDE.md, ADR-025): no shorting outside the
    paper-only `trader/perps/` package. It bought only on an SMA 20/50 cross-up and made no
    trade from Nov 15 to 22.
  - Nothing read a market trend centrally (`regimes/null_classifier.py` returns unknown).
  - EXP-2026-020 (BTC/ETH/SOL 4h, 2020-2026, 1x, held-back 2024-2026): SMA 50/200 long and
    short made about 24%/yr in the holdout against -3%/yr for `tsmom_30d` long and short.
    Shorts paid in bear markets (2022) and cost in bull markets. EXP-2026-019 (spot thread,
    Coinbase, 3 years) found the same order, and the 1x perps long+short variant best.
  - EXP-2026-021: every pair with a slow average of 150-200 candles made about 20-26%/yr in
    the holdout; 50/200 sits in the middle of that plateau. The development winner (10/300)
    fell to 4%/yr. Switching to SMA 10/30 when the 30-day efficiency ratio is below 0.05
    did a little better in both periods (development 101%/yr, Sharpe 1.36; holdout 26%/yr,
    Sharpe 0.71, against 84%/1.21 and 24%/0.67 for plain 50/200) with about 4x the trades
    (about 20 a month across three coins); nearby thresholds (0.10, 0.15) did worse, so the
    edge is fragile. This is the variant the owner chose.
- **Decision:**
  1. `trader/regimes/trend.py` is the one place the trend is defined: up while the 50-bar
     average of closes is above the 200-bar average, down while below; while the market is
     ranging (Kaufman efficiency ratio of the last 180 candles, 30 days, below 0.05) the
     10/30 averages decide instead. Unknown during warm-up (fewer than 200 closes) or when
     the deciding averages are equal. Every perps account reads it on 4h candles (degen's hourly sweep
     already reads its trend from 4h candles, ADR-040): 50 candles is about 8 days, 200
     about 33 days; 10 and 30 candles are about 2 and 5 days.
  2. New perps signal `trend_50_200_range_10_30` (long in an uptrend, short in a downtrend, flat
     only during warm-up) becomes `DEFAULT_SIGNAL`, so `perps` and `perps-degen` switch to
     it when restarted. `tsmom_30d` and the others stay selectable with `--signal`.
  3. New paper account `spot-perps` (`configs/perps/jupiter-spot-perps.yaml`, compose
     service `perps-spot-perps`, alerts `[spot perps]`) runs the same rule both ways at 1x,
     with no liquidation buffer, so spot's strategy can go short without spot code ever
     shorting. The CLI pins this account to `trend_50_200_range_10_30`; any other `--signal` exits 2.
  4. Spot's `sma_stance` (ADR-043) takes its up/down decision from the same `trend_state`,
     so the comparison lives in one place. It stays long-only and keeps the plain 50/200
     pair: the 10/30 range switch was not backtested at spot costs (EXP-2026-018 used 50 bps
     a side), so adding it to spot needs `research/run_exp018.py` re-run with that rule.
- **Consequences:** The running main and degen runs used `tsmom_30d`, so each must be
  archived (`perps paper reset --reason`, ADR-041) before restarting; a saved run with a
  different signal refuses to resume (RUNBOOK 2e). In trends a position is held for weeks; in
  ranges the fast pair flips often, so expect about 20 trades a month across three coins,
  more fees, and more stops. Every trade keeps its stop (ADR-042). The dashboard does not show
  `spot-perps` yet. Results are from past prices, spot data standing in for perps, without
  funding; they are not a forecast and profit is not guaranteed.
