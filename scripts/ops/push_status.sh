#!/usr/bin/env bash
# Status push (ADR-047): copy the health snapshot, reports, state and event logs to the
# private crypto-trader-ops repo so scheduled reviews can read them without server access.
# The server's key for that repo cannot write to the bot code repo.
source "$(dirname "$0")/common.sh"
take_lock 300
trim_log push_status.log

if [ ! -d "$OPS_REPO_DIR/.git" ]; then
  git clone --quiet "$OPS_REMOTE" "$OPS_REPO_DIR"
fi
dest="$OPS_REPO_DIR"
mkdir -p "$dest/reports" "$dest/state" "$dest/logs"
cp -f data/ops/health.json "$dest/health.json" 2>/dev/null || true
cp -rf data/reports/. "$dest/reports/" 2>/dev/null || true
# Reason: state and event logs are small JSON; secrets never live under data/.
find data/state -maxdepth 1 -name '*.json' -exec cp -f {} "$dest/state/" \; 2>/dev/null || true
find data/logs -maxdepth 1 -name '*.jsonl' -exec cp -f {} "$dest/logs/" \; 2>/dev/null || true
git log -1 --format='%H %cI %s' >"$dest/deployed-commit.txt"
# Reason: lets scheduled reviews confirm a deploy took effect (each service's start line) and
# that the dashboard is reachable over Tailscale, without a login to the server.
{
  echo "## deployed (last auto-deploy)"; cat "$OPS_STATE/deployed-sha" 2>/dev/null || echo none
  echo; echo "## auto-deploy hold"; head -1 "$OPS_STATE/deploy-hold" 2>/dev/null || echo off
  echo; echo "## containers"; docker compose ps --format '{{.Service}} {{.State}} {{.Status}}' 2>&1
  echo; echo "## tailscale serve"; tailscale serve status 2>&1 | head -20 || echo "tailscale not installed"
  for svc in "${PAPER_SERVICES[@]}"; do
    echo; echo "## logs: $svc (last 15 lines)"; docker compose logs --no-color --tail 15 "$svc" 2>&1
  done
} >"$dest/server-info.txt" 2>&1

cd "$dest" || exit 1
# Reason: the daily scheduled review commits its reports under reviews/ in the same repo
# (ADR-048), so pick those up first; the server never writes reviews/, so this cannot conflict.
git pull --quiet --rebase origin main 2>/dev/null || true
git add -A
git -c user.name="crypto-trader server" -c user.email="ops@localhost" \
  commit --quiet -m "status $(date -u +%FT%TZ)" || exit 0
git push --quiet origin HEAD:main
