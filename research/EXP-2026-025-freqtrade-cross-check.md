# EXP-2026-025: freqtrade cross-check of the main bot's replay (research only)

- **Asked:** owner, 2026-11-26 ("run our strategy through its backtester as a second opinion.
  It also catches strategies that accidentally peek at future prices").
- **Question:** does an independent, widely used backtester (freqtrade 2026.10) reproduce
  our replay of the `main` paper account, and does it find any look-ahead?
- **Nothing live changed.** The strategy lives in `research/freqtrade/` only.

## Setup

- Data: Binance BTC, ETH, SOL 4h (and 1h) candles to 2026-11-21, the same files the
  EXP-2026-022/023 replays used (`/Users/daharimorgan/dev/data/stop-research/`).
- Our side: the EXP-2026-023 harness (`exp023_lib.run`, the real `PaperPerpsAccount`) with
  `configs/perps/jupiter.yaml` v11. Borrow set to 0 on our side because freqtrade has no
  equivalent fee (funding files are zero), so both sides pay only the 7 bps a side.
- freqtrade side: `research/freqtrade/user_data/strategies/TrendMain.py`, a port of the
  shared trend rule (50/200 averages, 10/30 while the 30-day efficiency ratio is below
  0.05), leverage from 4 typical daily moves (1x-25x), 10% of equity per position, 3
  positions, 400% total size cap, 30% stop on collateral with fees, the 4/8/12R ladder
  (25/25/50) with the stop moves, and the next-UTC-day wait after a stop or TP3.
  `TrendMainNoLadder` is the same without the ladder.
- The container cannot reach an exchange, so `ft_offline.py` hands freqtrade Binance
  USDT-M market metadata and one leverage tier with 0.2% maintenance (our 20 bps).
- Windows: 2020-10-01..2023-12-31 and 2024-01-01..2026-11-21, $2,500 start each.

## Results

Whole account (end balance from $2,500, worst drop from a peak):

| Variant, window | Our engine | freqtrade 4h | freqtrade 4h + 1h detail |
|---|---|---|---|
| No ladder, 2020-23 | $1,142,382, 58% | $915,573, 57% | |
| No ladder, 2024-26 | $39,449, 67% | $38,681, 70% | |
| Live ladder, 2020-23 | $196,390, 54% | $110,131, 53% | $136,923, 51% |
| Live ladder, 2024-26 | $25,533, 69% | $20,540, 67% | $22,339, 67% |

Trade by trade (`compare.py`):

| Variant, window | Trades ours / ft | Same coin, side and entry bar | Same leverage | Result within 1 pt of collateral | Mean result per trade, ours / ft |
|---|---|---|---|---|---|
| No ladder, 2020-23 | 909 / 921 | 99% | 100% | 99% | +12.8% / +12.3% |
| No ladder, 2024-26 | 873 / 876 | 99% | 100% | 100% | +5.8% / +5.8% |
| Ladder, 2020-23 | 995 / 1007 | 99% | 100% | 93% | +6.2% / +5.4% |
| Ladder, 2024-26 | 918 / 919 | 99% | 100% | 94% | +4.2% / +3.9% |
| Ladder, 2020-23, 1h detail | 995 / 998 | 100% | 100% | 94% | +6.2% / +5.7% |
| Ladder, 2024-26, 1h detail | 918 / 916 | 100% | 100% | 95% | +4.2% / +4.0% |

Look-ahead checks:

- `lookahead-analysis` (60 trades, 2022-2023): **no bias** in any indicator, entry or exit.
- Positive control `TrendMainPeek` (reads the next candle's close on purpose): flagged as
  biased on `trend` and every signal column, so the check does catch peeking.
- `recursive-analysis` (startup 420 vs 600 vs 1000 candles): **no variance** and no
  indicator look-ahead.

## What it means

1. **The signal, leverage, sizing and stop code agree with an independent backtester.**
   Without the ladder 99-100% of trades are the same trade with the same leverage and the
   same result. The whole-account gap on 2020-23 (about 20%) is compounding of the ~1% of
   trades that differ: freqtrade cannot open the other side in the same candle it closes a
   position, so a flip waits one bar.
2. **The ladder is where our replay is kinder.** Our engine fills each take-profit exactly at
   its level; freqtrade can only scale out at the next candle's open after the level was
   touched (the next 1h open with detail). That costs 0.2-0.8 points of collateral per trade,
   and 44% of the end balance on 2020-23 at 4h (30% with 1h detail), 12-20% on 2024-26. A
   resting take-profit order would fill at the level, so the truth is probably between the
   two, closer to ours; treat replay numbers with the ladder as a little optimistic.
3. **No look-ahead** in the trend rule or the leverage measure, confirmed by freqtrade's own
   tools, matching the EXP-2026-023 audit.
4. Not modelled on either side here: borrow (on our side it cuts the 2020-23 end balance from
   $196k to $96k and 2024-26 from $26k to $10k), funding, the 15% daily loss limit (fired
   0-2 times per window in our replay), and Binance vs Kraken prices. Replays are not
   forecasts; 2024-26 has been looked at by 20+ experiments.

## Reproduce

```
uv venv ft-venv --python 3.12 && . ft-venv/bin/activate && uv pip install freqtrade==2026.10
cd research/freqtrade && freqtrade create-userdir --userdir user_data
python -I convert.py <candle dir> user_data/data
python ft_offline.py backtesting -c config.json -s TrendMain --timerange 20240101-20261121 --export trades
python ft_offline.py lookahead-analysis -c config.json -s TrendMain --timerange 20220101-20240101
python ft_offline.py recursive-analysis -c config.json -s TrendMain --timerange 20230101-20240101 --startup-candle 420 600 1000
uv run python research/freqtrade/ours_replay.py <candle dir> <cache dir> <out dir>   # needs exp023_lib.py
python compare.py "label,<out dir>/ours-ladder-hold.json,user_data/backtest_results/<run>.zip"
```
