#!/usr/bin/env bash
# Start a paper service that a deploy added (ADR-051). Auto-deploy reads PAPER_SERVICES
# before it pulls, so a service the deployed commit adds is not started by that deploy.
# When the last deploy built exactly the commit on disk and the stack is up, this creates
# any listed paper service that has no container yet.
# It never builds, so it never deploys code (that is auto-deploy's job, and it respects the
# hold); it never touches a container that exists, running or stopped, so a bot the owner
# stopped stays stopped; and `live` is not in PAPER_SERVICES, so it can never start it.
# Runs at the start of every watchdog run.
source "$(dirname "$0")/common.sh"
take_lock 120

# Reason: seconds a new account gets to write its first state before the health check runs.
# The ten-coin account's first cycle is twenty candle requests a second apart, so about 40
# seconds; 90 leaves room for a retried request.
WAIT="${NEW_SERVICE_WAIT:-90}"

deployed="$(cat "$OPS_STATE/deployed-sha" 2>/dev/null || true)"
[ -n "$deployed" ] && [ "$deployed" = "$(git rev-parse HEAD 2>/dev/null || true)" ] || exit 0

present=0
missing=()
for svc in "${PAPER_SERVICES[@]}"; do
  if [ -n "$(docker compose ps --all -q "$svc" 2>/dev/null || true)" ]; then
    present=1
  else
    missing+=("$svc")
  fi
done
# Reason: after `docker compose down` no paper service has a container; that is the owner's
# choice, so nothing is started.
[ "$present" = 1 ] || exit 0

started=0
for svc in ${missing[@]+"${missing[@]}"}; do
  marker="$OPS_STATE/start-failed-$svc"
  if docker compose up -d --no-build "$svc" >/dev/null 2>&1; then
    notify "started the new service $svc"
    rm -f "$marker"
    started=1
  elif [ ! -f "$marker" ] || [ -n "$(find "$marker" -mmin +360)" ]; then
    # Alert now, then at most every 6 hours while it keeps failing.
    date -u +%FT%TZ >"$marker"
    notify "could not start the new service $svc. Logs: docker compose logs --tail 50 $svc"
  fi
done
[ "$started" = 0 ] || sleep "$WAIT"
