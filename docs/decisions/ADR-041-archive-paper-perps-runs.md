# ADR-041: Archive every paper perps run instead of wiping it on reset

- **Status:** Accepted (2026-11-19; owner request: "archive each run for improvements sake")
- **Context:** A paper perps account was reset by moving or deleting
  `data/state/<stem>.json` by hand (RUNBOOK 2c/2d). That kept no equity curve and no summary,
  and the old run's trades stayed mixed into the live event log. Two runs of the main account
  were reset while ahead (one peaked at $2,801), so their results were effectively lost and
  later comparisons were not honest about what earlier settings had done.
- **Decision:**
  1. `trader perps paper reset --reason "..." [--account degen]` archives the current run:
     it writes `summary.json` and moves (never copies or deletes) the state file, the event
     log and the equity log into `data/archive/perps/<stem>/<start>__<end>/`. The summary
     holds settings (signal, timeframe, config version), start and final equity, P&L in
     dollars and percent, peak equity, largest drop, fees, and from the event log the closed
     trades, wins, losses, stops and liquidations. A reason is required; an existing folder
     is never overwritten.
  2. Each session also appends one line per processed bar to
     `data/logs/<stem>-equity.jsonl` (time, equity, peak), so an archived run keeps its full
     equity curve, not only the start and day-change points in the event log.
  3. A running session that finds its state file gone (archived under it) refuses to save or
     append events, alerts once and exits; Docker's restart policy then starts a fresh run.
     This stops a forgotten `docker compose stop` from resurrecting the archived run.
  4. `trader perps paper runs [--account degen]` lists archived runs, plus older
     `data/state/<stem>-*.json` files moved aside by hand (their saved `meta` still has start,
     final and peak equity).
- **Consequences:** Resetting is now lossless and auditable. The live logs only cover the
  current run, so the dashboard shows that run alone; past runs are read with `runs` or from
  the archive folder. The archive lives in the git-ignored `data/` volume, so it is as durable
  as the server's disk (back it up with the rest of `data/`). Paper only: nothing here
  trades, signs or reads a key (ADR-025).
