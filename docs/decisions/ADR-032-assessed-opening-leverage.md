# ADR-032: Each paper perps position opens at a leverage assessed from volatility

- **Status:** Accepted (2026-11-12; owner decision UD-26)
- **Owner decision UD-26 (2026-11-12):** leverage "should be adjusted based on market
  conditions"; "not during the trade, just each opening position size is assessed and not
  fixed". Safety buffer chosen by the owner: **4** typical daily moves.
- **Context:** Every position opened at one fixed leverage (12x after UD-25), so the bot
  used the same leverage on a calm coin and on a coin swinging twice as hard.
- **Decision:**
  1. New optional risk value `liquidation_buffer_daily_moves`. When it is set, a new
     position opens at the leverage that puts its liquidation price that many typical daily
     moves away: `1 / (buffer x daily move + closing fee + maintenance)`, rounded down to
     one decimal, never below 1 and never above `target_leverage` (now the ceiling).
  2. The typical daily move is the standard deviation of bar-to-bar returns over the last
     30 days, scaled to one day, per market, using closes up to the decision bar only.
  3. The leverage is fixed for the life of the position; nothing is resized during a trade.
  4. Deterministic risk code computes it (`opening_leverage` in `trader.perps.risk`);
     strategies still only say long, short, or flat. Every existing limit still applies
     (the 8% minimum liquidation distance, 25x maximum, per-position and total-size caps).
  5. Fail closed: with fewer than 30 days of candles the volatility is unknown and the open
     is refused (`PERP_VOLATILITY_UNAVAILABLE`). A `TBD` buffer makes the configuration
     unusable (exit 3), like every other perps value.
  6. The replay and the forward session use the same rule; the opening leverage is written
     to each `OPENED` event and shown in the phone alert.
- **Consequences:** With the approved values (ceiling 12x, buffer 4), a coin moving about 2%
  a day opens at 12x, about 2.4% at 10x, about 3% at 8x, and about 6% at 4x. The 30-day
  window reacts slowly to a sudden change in volatility. Whether assessed leverage beats
  fixed leverage in dollars is not yet tested on history; that belongs to the strategy
  research track.
