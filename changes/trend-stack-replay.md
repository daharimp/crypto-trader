### Added
- Research: exploratory replays on past prices (paper only, no configuration change):
  `research/degen_replay.py` (1h/4h/1d alignment, 2 daily moves of leverage) and
  `research/trend_stack_replay.py` (1D direction, 1H structure, 15M trigger, 6 of 7 checks,
  swing stop, trailing exit, leverage from stop distance), with results in
  `research/degen-replay-results.txt` and `research/trend-stack-replay-results.txt`.
  `research/degen2_replay.py` (one shared account, follow the volume, TP ladder), results in
  `research/degen2-replay-results.txt`. `research/bigger_bets_replay.py` (running rule at 4, 3, 2 daily moves and a volume tilt) and
  `research/candle_replay.py` (a decision at every 4h close), both in 12-hour blocks, results
  in `research/bigger-bets-replay-results.txt` and `research/candle-replay-results.txt`.
  `scripts/fetch_coinbase_history.py` gains a `15m` option.
