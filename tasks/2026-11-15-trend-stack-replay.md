# 2026-11-15: Trend-stack replay (Longatron-inspired ideas, paper research only)

Owner request: borrow ideas from the owner's old Longatron GPT (1D direction, 1H structure,
15M trigger, confidence threshold, stop on every trade) and judge on recent weeks against
the running paper perps account. Not a copy of Longatron.

- [x] Degen replay (1h/4h/1d alignment, 2 daily moves) and results
- [x] Trend-stack replay coded and committed before any result (`bc3d47f`)
- [x] Data re-downloaded (15m 730 days; 4h; Deribit funding), replay run, results saved
- [x] Fee drag measured: about +$10.9k before fees, about $17.3k fees, whole account 99 weeks
- [x] Owner's Longatron answers and one worked example (SOL short, 2026-04-06) received
- [x] Degen v2 replay (one shared account, follow the volume, TP ladder), committed before
      any result (`5fd0fc6`), run and recorded
- [x] Bigger-bets replay on the running rule, 12-hour blocks (`e2f6edb`, committed before results)
- [x] Candle replay, a decision at every 4h close (committed before results)
- [x] Guarded replay of the owner's plan (`9525990`, committed before results); confidence
      measure found flawed (never above 50%), disclosed in the results
- [ ] Owner: choose a better confidence measure, then pre-register and rerun
- [ ] Owner: any further Longatron rules (indicator settings, confidence scoring, SL/TP/leverage
      rules, DEGEN MODE) and any past trade records
- [ ] Owner decides whether any variant deserves a separate paper account (needs
      owner-approved values; not started)

Test inputs only (20% / 50% of collateral at risk, 25x cap, $250, 7 bps fee); none is an
approved risk value.
