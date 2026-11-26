# 2026-11-26: Alert when the status push fails (daily review finding)

The ops repo received no status push from 2026-11-24 00:20 UTC to at least 2026-11-26
00:40 UTC, and nothing told the owner. `push_status.sh` had no alert, and a held ops lock
made it exit 0 silently.

- [x] `streak_fail` / `streak_ok` in `scripts/ops/common.sh`: alert on the 2nd failure in a
      row, every 24 more, and on recovery
- [x] `take_lock` takes an optional on-skip callback; `push_status.sh` counts skips and errors
- [x] Tests: `tests/unit/test_ops_push_alert.py`
- [ ] Owner: find and fix why the server stopped pushing (not fixable from this change)
