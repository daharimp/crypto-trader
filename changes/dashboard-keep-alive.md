### Added
- `scripts/ops/dashboard_check.sh`: every 5 minutes (and each watchdog run) checks that the
  dashboard page answers, restarts only the dashboard if not, alerts the phone, and alerts if
  Tailscale stops serving it (ADR-050). Compose healthcheck on the dashboard.

### Fixed
- Dashboard server: 30 s request timeout so abandoned connections cannot pile up, one shared
  candle fetch per minute, and last good candles served when Kraken fails (ADR-050).
