#!/usr/bin/env bash
# Dashboard keep-alive (ADR-050): make sure the page answers, not just that the container runs.
# Probes the dashboard on the server's localhost; if it does not answer, restarts only the
# dashboard container and alerts the owner's phone. Also checks that Tailscale still serves it.
# Runs every 5 minutes from cron and at the start of every watchdog run.
source "$(dirname "$0")/common.sh"
take_lock 120
trim_log dashboard.log

URL="${DASHBOARD_URL:-http://127.0.0.1:8787}"
TRIES="${DASHBOARD_PROBE_TRIES:-3}"
DELAY="${DASHBOARD_PROBE_DELAY:-10}"
WAIT="${DASHBOARD_RESTART_WAIT:-20}"
# Reason: a dashboard that dies again right after each restart needs a person, not a loop.
MAX_RESTARTS_PER_HOUR="${DASHBOARD_MAX_RESTARTS:-3}"
down="$OPS_STATE/dashboard-down"
restarts="$OPS_STATE/dashboard-restarts"
mkdir -p data/ops

# Reason: /api/status reads only local files, so a slow Kraken or Jupiter cannot fail it; the
# page itself (/) proves the static files are served too.
probe() {
  curl -fsS -o /dev/null -m 15 "$URL/" && curl -fsS -o /dev/null -m 15 "$URL/api/status"
}
answers() {
  local i
  for ((i = 1; i <= TRIES; i++)); do
    probe && return 0
    [ "$i" -lt "$TRIES" ] && sleep "$DELAY"
  done
  return 1
}
record() { echo "$(date -u +%FT%TZ) $*" | tee data/ops/dashboard.txt; }
# Alert now, then at most every 6 hours for the same problem (marker file holds the time).
alert_every_6h() {
  local marker="$1"; shift
  if [ ! -f "$marker" ] || [ -n "$(find "$marker" -mmin +360)" ]; then
    date -u +%FT%TZ >"$marker"
    notify "$*"
  fi
}

check_tailscale() {
  command -v tailscale >/dev/null 2>&1 || return 0
  local marker="$OPS_STATE/tailscale-serve-missing"
  if tailscale serve status 2>&1 | grep -q '8787'; then
    if [ -f "$marker" ]; then
      notify "Tailscale is serving the dashboard again"
      rm -f "$marker"
    fi
    return 0
  fi
  alert_every_6h "$marker" "dashboard runs but Tailscale is not serving it, so your phone can't open it. Fix on the server: sudo tailscale serve --bg 8787"
}

if answers; then
  if [ -f "$down" ]; then
    notify "dashboard is back up"
    rm -f "$down"
  fi
  record "ok"
  check_tailscale
  exit 0
fi

# Not answering. Count recent restarts, then restart only the dashboard.
touch "$restarts"
recent="$(awk -v cutoff="$(($(date +%s) - 3600))" '$1 >= cutoff' "$restarts" | wc -l)"
if [ "$recent" -ge "$MAX_RESTARTS_PER_HOUR" ]; then
  record "down; not restarting ($recent restarts in the last hour)"
  alert_every_6h "$down" "dashboard keeps failing ($recent restarts in the last hour); stopped restarting it. Logs: docker compose logs --tail 50 dashboard"
  exit 1
fi
date +%s >>"$restarts"
tail -n 50 "$restarts" >"$restarts.tmp" && mv "$restarts.tmp" "$restarts"

# Reason: --no-build reuses the deployed image, so this never deploys new code (that is
# auto-deploy's job, and it respects the hold). restart covers a hung but running process.
if docker compose ps --status running --services 2>/dev/null | grep -qx dashboard; then
  docker compose restart dashboard >/dev/null 2>&1 || true
else
  docker compose up -d --no-build dashboard >/dev/null 2>&1 || true
fi
sleep "$WAIT"

if answers; then
  record "restarted; ok"
  notify "dashboard was not answering; restarted it and it is back up"
  rm -f "$down"
  check_tailscale
  exit 0
fi
record "down after restart"
alert_every_6h "$down" "dashboard is DOWN and a restart did not fix it. Logs: docker compose logs --tail 50 dashboard"
exit 1
