# ADR-042: A stop-loss on every paper perps account, 50% of collateral on the main account

- **Status:** Accepted (2026-11-19; owner decision UD-31)
- **Owner decision UD-31 (2026-11-19):** after a health report on the paper bots, the owner
  approved adding a stop-loss to the main perps account, reusing the degen account's
  mechanism, with "a sensible default, configurable", and added: "always assess a stop
  loss". The 50% value below was chosen in this ADR; merging the pull request that adds it
  is the owner's approval of the number, and it can be changed like any other setting.
- **Context:** The main account (`configs/perps/jupiter.yaml`, 4h, `tsmom_30d`) opens each
  position at the leverage that keeps liquidation 4 typical daily moves away (UD-26, up to
  25x; about 11x in recent markets) with 10% of equity as collateral, and had no stop. A
  position could only end by signal flip or liquidation (100% of its collateral). In the
  replay of its settings (`research/guarded-replay-results.txt`, RUN4, past prices, not a
  forecast) it had 7 liquidations and an 85% worst drop. The same rule with the degen
  account's 30% stop (OWNER vs OWNER_NOSTOP, 5% collateral, buffer 3) went from 21
  liquidations to 0, from a 66% to a 55% worst drop, and ended higher ($38,626 vs $30,423).
  Spot already sizes every entry from a required hard stop (UD-16) and rests a protective
  stop after each fill, so spot needs no change.
- **Decision:**
  1. `risk.stop_loss_pct_of_collateral` is required in every perps config file. A file
     without it fails closed with exit 3 (`PERPS_CONFIG_UNRESOLVED ... (UD-31)`), the same
     as a `TBD`. The mechanism is unchanged from ADR-038 (fees and borrow included; a gap
     fills at the open; past liquidation is a liquidation; the market waits for the next UTC
     day). Parameters built in code for research may still omit it.
  2. The main account sets it to **50%** (`jupiter.yaml` v10). Why 50 and not degen's 30:
     - With volatility-assessed leverage the liquidation price sits about 4 typical daily
       moves from entry, so a stop at a share of collateral is really a distance in daily
       moves: 50% puts it about **2 daily moves** away, half way to liquidation. Degen's 30%
       with a buffer of 3 sits about 0.9 daily moves away and fired on 363 of 1,134 replay
       trades; the 4h trend rule wins about 1 trade in 3 and earns from a few long runs
       (`research/degen2-replay-results.txt`: early exits clipped those runs), so a stop
       inside a day's normal move would mostly cut winners early.
     - It caps one trade's loss at about **5% of equity** (10% collateral x 50%), plus any
       gap past the stop, instead of 10% at liquidation; three open positions risk about 15%,
       the same as the daily loss limit.
     - When the 25x ceiling binds (calm markets, liquidation closer than 4 daily moves), the
       stop is proportionally closer too, which is the cautious direction.
  3. Not done here: a stop-level sweep on the main account's settings. The replay data
     (Coinbase candles, Deribit funding) cannot be downloaded from the build environment;
     running `research/guarded_replay.py` with stops of 30-70% on buffer 4 / 10% collateral
     is the follow-up that would confirm or move the 50%. A stop set directly from volatility
     (2-3 daily moves, ATR-style) with leverage as an output is a separate proposal for the
     owner, not decided here.
- **Consequences:** Main-account positions now end at about -5% of equity at worst instead of
  -10%, and liquidations should become rare (only on a gap through the stop). Expect some
  trades to be stopped and then sit out the rest of the UTC day. The running main account
  picks up the stop on its next restart with the new config; existing positions get it at
  once, since the stop is computed from each position's collateral at every bar.
