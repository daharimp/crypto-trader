### Fixed
- `scripts/ops/push_status.sh`: commits the snapshot before syncing, rebases onto the ops
  repo's main (merge fallback, never force-push, never drops `reviews/`), retries once, and
  sends a phone alert when the push fails and when it recovers (ADR-047 amendment).
- `scripts/ops/common.sh`: `notify` reads `.env` by full path, so alerts work from any
  directory.
