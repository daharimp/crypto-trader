### Fixed
- `scripts/ops/push_status.sh` now sends a phone alert when the hourly status push fails or
  is skipped because the shared ops lock is held, on the second run in a row, then about
  once a day while it stays broken, and once when it recovers (ADR-047). Before, a failed
  push only went to `push_status.log`, so the ops repo could go quiet for days unnoticed.
