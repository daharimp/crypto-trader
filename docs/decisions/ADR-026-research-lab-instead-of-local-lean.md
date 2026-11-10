# ADR-026: In-repo research lab; QuantConnect for outside confirmation

- **Status:** Accepted (2026-11-10; owner asked for a QuantConnect research setup)
- **Context:** The perps baseline loses on real data. The owner asked for QuantConnect to
  test strategy ideas faster. In this cloud session LEAN cannot run locally (no Docker
  daemon; the engine image is about 14 GB), and QuantConnect's API signs each request with
  the user's token, which the session's credential injection cannot do without exposing it.
- **Decision:**
  1. `trader.research.lab`: a small, tested research harness on real 4h candles: signals
     decided at close *i* and filled at open *i+1*, costs per side and hourly borrow, three
     walk-forward folds, buy-and-hold per fold, and a sealed 180-day holdout that is opened
     once for ideas chosen beforehand (`research/run_holdout.py`).
  2. Ideas that survive are re-implemented in LEAN Python (`research/lean/`) so the owner
     can confirm them on QuantConnect's data in its web IDE. Those files are untested here.
  3. The lab is never imported by the trading pipeline. A strategy reaches paper trading only
     as a registered strategy class with tests, through the risk engine and the gates.
- **First results (EXP-2026-010):** no idea is robust across all coins and periods. The best,
  a long-only volatility-squeeze breakout, beat buy-and-hold in 7 of 9 fold tests at Kraken
  spot costs and in 3 of 3 holdout tests, with drawdowns at or below 21%, but on only 3 to 8
  trades per test. At the cautious perps borrow (0.01%/h, about 88% of position size per
  year), multi-day holds on Jupiter cannot overcome costs.
