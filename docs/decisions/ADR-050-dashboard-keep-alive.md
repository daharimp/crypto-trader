# ADR-050: Dashboard keep-alive: probe the page, restart only the dashboard, alert the phone

- **Status:** Accepted (2026-11-26; owner asked "why does the dashboard keep crashing, how do
  we keep this up" in the project thread)
- **Context:** The hourly snapshots showed the dashboard container running for two days
  without a restart (its only restart was the Nov 26 auto-deploy), yet the owner saw the page
  fail. The watchdog (ADR-047) only checks that containers are *running*; a process that is
  hung, or a Tailscale serve that stopped, looks healthy to it. The server (ADR-026) had no
  socket timeout, so clients that open a connection and never finish (a sleeping phone or
  laptop behind the Tailscale proxy) could each hold a thread forever, and every page load
  could trigger its own Kraken fetch when the minute cache expired.
- **Decision:**
  1. `scripts/ops/dashboard_check.sh` probes `/` and `/api/status` on `127.0.0.1:8787` (3
     tries, 10 s apart). `/api/status` reads only local files, so a slow price feed cannot
     fail it. If the page does not answer, it restarts **only** the dashboard (`restart` if
     running, `up -d --no-build` if not: never a build, so it never deploys code and the
     deploy hold still applies), waits, and probes again.
  2. Alerts go through the existing `ALERT_WEBHOOK_URL`: on a restart, when it stays down
     (then at most every 6 h), and when it is back. More than 3 restarts in an hour stops the
     restarting and alerts, so a broken build cannot loop.
  3. It also alerts (every 6 h at most) when `tailscale serve status` no longer forwards
     8787, with the one-line fix, since then the phone and laptop cannot open the page even
     though the server is fine.
  4. It runs every 5 minutes from cron (`install.sh`) and at the start of every 15-minute
     watchdog run, so servers whose crontab predates this still get it after auto-deploy.
     It shares the ops lock, so it never runs during a deploy.
  5. The server sets a 30 s request timeout, ignores clients that hang up, lets concurrent
     requests share one candle fetch, and serves the last good candles if a refresh fails.
  6. Compose gets a `healthcheck` on the dashboard so `docker compose ps` shows
     `(healthy)`/`(unhealthy)`. The last check result is in `data/ops/dashboard.txt` and the
     hourly `server-info.txt`.
- **Consequences:** A hung dashboard is back within about 5 minutes and the owner hears about
  it. Bot services are never restarted by this check. Problems on the viewing device itself
  (Tailscale switched off on the Mac or phone, browser secure DNS) cannot be fixed from the
  server; the runbook lists them.
