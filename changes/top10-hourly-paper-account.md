### Added
- Paper perps account `top10` (ADR-051, UD-33): the shared trend rule on BTC, ETH, BNB, XRP,
  SOL, TRX, HYPE, ZEC, DOGE and LINK, decided every hour, 1% of equity per position at 5x or
  less, 30% stop with the 4/8/12R ladder. Service `perps-top10`, settings
  `configs/perps/top10.yaml`, alerts `[perps top10]`. Paper only; it models no venue.
- `venue: generic_perps` for perps settings files: any coin with a public candle feed, no
  price mint. Jupiter files keep their rules.
- `scripts/ops/start_new.sh`: the watchdog creates a paper service that the last deploy
  added; it never builds and never touches an existing container.
- Paced, retried candle requests for accounts that read many markets
  (`trader/perps/candles.py`).

### Fixed
- Paper perps borrow fees accrue exactly and are paid in whole cents at a close or
  take-profit. Rounding each accrual to a cent charged nothing on hourly positions under
  about $300 and mis-charged small 4h ones. Saved runs continue; nothing is reset.
- `perps paper run` refuses to start an account that names a coin without a candle feed
  (exit 2) instead of failing every cycle.
