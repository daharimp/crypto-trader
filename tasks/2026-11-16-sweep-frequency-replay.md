# 2026-11-16: Sweep frequency replay (owner: "it should sweep more often for trades")

- [x] Hourly vs 4-hourly decisions for tsmom_30d, buffers 4 and 3, committed before results
- [x] Result: within noise; twice the trades and fees, fewer liquidations
- [ ] Owner: decide whether to try hourly on the degen account only (needs 4h volatility in the
      1h session; never on the main account during its 7-day test)
