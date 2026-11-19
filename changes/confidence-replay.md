### Added
- Research: `research/confidence_replay.py`, an exploratory replay of confidence measured at
  every 4h close (past 3-day outcomes by trend strength and agreement, no look-ahead), sizing
  5-15% by confidence and adding more at 85%+, with a calibration check; results in
  `research/confidence-replay-results.txt`. Paper research only; no configuration change.
