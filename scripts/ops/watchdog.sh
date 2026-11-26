#!/usr/bin/env bash
# Watchdog (ADR-047): every 15 minutes, check the paper bots and alert only on problems.
source "$(dirname "$0")/common.sh"
# Reason: runs first, under its own lock, so a hung dashboard is restarted even on servers
# whose crontab predates the 5-minute dashboard job (ADR-050).
bash "$(dirname "$0")/dashboard_check.sh" || true
# Reason: a service added by the last deploy is created here, under its own lock, before the
# health check counts it as missing (ADR-051).
bash "$(dirname "$0")/start_new.sh" || true
take_lock 120
trim_log watchdog.log

mkdir -p data/ops
docker compose ps --all --format json >data/ops/containers.json 2>/dev/null || : >data/ops/containers.json
docker compose logs --no-color --since 20m "${PAPER_SERVICES[@]}" >data/ops/recent-logs.txt 2>&1 || true
if ! docker compose run --rm -T cli ops health \
    --containers data/ops/containers.json --logs data/ops/recent-logs.txt \
    --commit "$(git rev-parse --short HEAD)" --alert; then
  # Alert at most once an hour if the check itself cannot run.
  marker="$OPS_STATE/health-failed"
  if [ ! -f "$marker" ] || [ -n "$(find "$marker" -mmin +60)" ]; then
    touch "$marker"
    notify "watchdog: the health check itself failed to run on the server"
  fi
  exit 1
fi
rm -f "$OPS_STATE/health-failed"
