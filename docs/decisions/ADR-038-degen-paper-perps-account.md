# ADR-038: A second, separate paper perps account with its own settings ("degen")

- **Status:** Accepted (2026-11-15; owner decision UD-29)
- **Owner decision UD-29 (2026-11-15):** after the replays in PR #38 and
  `research/confidence-replay-results.txt`, the owner approved a second paper account next to
  the running one, using the same rule (`tsmom_30d`, 4h) with: "3 is the floor" (a liquidation
  buffer of **3** typical daily moves); **5%** of equity per position; "a SL strat to prevent
  [more] than 30% loss of what [is] at risk during [the] trade" (a stop at **30%** of the
  position's collateral); and "if performance is bad that day a noti should be sent to stop
  and analyze for the rest of the day" (the existing **15%** daily loss limit, now with an
  alert). Coins: SOL, BTC, ETH. "All of the settings should be adjustable."
- **Context:** One paper perps account existed (`configs/perps/jupiter.yaml`,
  `data/state/perps-paper.json`). The owner wants to compare a more aggressive setup side by
  side with it, on live prices, without disturbing the running 7-day test.
- **Decision:**
  1. Each paper account has its own config file under `configs/perps/`, state file and event
     log, chosen with `--account` (`main`: `jupiter.yaml`, `perps-paper.*`, the default and
     unchanged; `degen`: `jupiter-degen.yaml`, `perps-degen.*`). Compose runs it as the
     separate `perps-degen` service. The kill switch stops both.
  2. New optional risk value `stop_loss_pct_of_collateral` (between 0 and 100, `TBD` fails
     closed). When set, at each completed bar a position whose adverse extreme reaches the
     price where it has lost that share of its collateral, opening and closing fees and borrow
     included, closes there (`CLOSED`, reason `STOP_LOSS`); if the bar opened beyond the stop
     it fills at the open; if the fill would be past liquidation it is a liquidation. The
     stopped market then opens nothing until the next UTC day, because the trend usually
     still points the same way and would reopen at once.
  3. When today's loss reaches `daily_loss_limit_pct` the account journals `DAY_HALTED` once
     per UTC day and sends a phone alert ("stop and analyze for the rest of the day"). The
     existing risk check already refuses new opens past the limit; open positions stay open,
     as in the replay that was approved (`B3_HALT15`/`OWNER`, not the close-everything variant).
     This alert also applies to the main account, whose behaviour is otherwise unchanged.
  4. Settings are adjusted by editing the account's file, raising `version`, updating the
     approval fields and restarting that account (RUNBOOK 2d). The dashboard shows them
     read-only on the **Degen · paper** view; it still cannot change anything (ADR-026).
  5. Deterministic risk code keeps final authority; strategies still only say long, short or
     flat. No keys, wallets, signing or transactions (ADR-025).
- **Consequences:** In the replay (past prices, not a forecast) this setup ended at $38,626
  from $2,500 since 2022-01-10 with a worst drop of 55%, against $36,702 and 85% for the
  main account's rule at its settings. The stop fires often (363 times in that replay), so
  expect many small stopped trades. Confidence-based sizing (5-15%) and "trade more at 85%"
  were tested and not built: the measured confidence never exceeded 66% and was not
  calibrated (`research/confidence_replay.py`, branch `research/confidence-replay`).
