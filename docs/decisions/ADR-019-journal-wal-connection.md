# ADR-019: Journal uses one WAL-mode SQLite connection per run

- **Status:** Accepted (implementation decision, M1)
- **Date (UTC):** 2026-11-01
- **Context:** The handoff (§7.11) requires one transaction per event, committed before the
  call returns, and journal-before-act. Opening a connection and fsyncing for every event made
  the 2-year vertical-slice backtest take about 100 s (44,669 events).
- **Decision:** `JournalStore` keeps one connection open per run with `journal_mode=WAL` and
  `synchronous=NORMAL`. Every event is still its own committed transaction. `close()`
  checkpoints the WAL into the main file.
- **Reason:** Commits remain atomic and survive application crashes, so journal-before-act and
  the hash chain are unaffected. Only an OS crash or power loss could drop the last few
  committed events, which is acceptable for research backtests on historical data.
- **Consequence:** The same backtest runs in about 16 s. Before forward paper sessions (BL-027),
  revisit `synchronous=FULL` for the paper environment.
- **References:** R-05, ADR-018, NFR-01.
