# 2026-11-26: Keep the dashboard up (owner request)

- [x] Dashboard probe + restart + phone alert, Tailscale serve check (ADR-050)
- [x] Server request timeout, shared candle fetch, stale-on-error candles
- [x] Compose healthcheck on the dashboard
- [ ] Owner (optional): re-run `bash scripts/ops/install.sh` for the 5-minute cron; without it
      the check still runs every 15 minutes with the watchdog
