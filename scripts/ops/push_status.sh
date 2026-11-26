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
  echo; echo "## dashboard check (ADR-050)"; cat data/ops/dashboard.txt 2>/dev/null || echo "not run yet"
  echo; echo "## tailscale serve"; tailscale serve status 2>&1 | head -20 || echo "tailscale not installed"
  for svc in "${PAPER_SERVICES[@]}"; do
    echo; echo "## logs: $svc (last 15 lines)"; docker compose logs --no-color --tail 15 "$svc" 2>&1
  done
} >"$dest/server-info.txt" 2>&1

cd "$dest" || exit 1
# Reason: a run killed mid-rebase would leave the clone stuck; start every run clean.
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then git rebase --abort || true; fi
if [ -f .git/MERGE_HEAD ]; then git merge --abort || true; fi

# Reason: commit before syncing. The old `git pull --rebase` ran with the fresh snapshot still
# uncommitted, so git refused ("unstaged changes"), the error was hidden, and once the daily
# review committed reviews/ upstream every push was rejected as non-fast-forward (Nov 24-26).
git add -A
git -c user.name="crypto-trader server" -c user.email="ops@localhost" \
  commit --quiet -m "status $(date -u +%FT%TZ)" || true

# Replay the server's commits on top of the ops repo's main (which may hold new reviews/
# commits from the scheduled review). Never force-pushes and never drops remote commits.
sync_with_remote() {
  git fetch --quiet origin main || return 1
  git rebase --quiet origin/main >/dev/null 2>&1 && return 0
  git rebase --abort >/dev/null 2>&1 || true
  # Reason: fallback for a file both sides changed. A merge keeps every remote commit
  # (reviews/ included); -X ours lets the server's newer snapshot win inside its own files.
  git -c user.name="crypto-trader server" -c user.email="ops@localhost" \
    merge --quiet --no-edit -X ours origin/main >/dev/null 2>&1 && return 0
  git merge --abort >/dev/null 2>&1 || true
  return 1
}

ahead() { [ -n "$(git rev-list -1 origin/main..HEAD 2>/dev/null)" ]; }

pushed=0
for attempt in 1 2; do
  if sync_with_remote; then
    if ! ahead || git push --quiet origin HEAD:main; then pushed=1; break; fi
  fi
  [ "$attempt" = 1 ] && sleep "${PUSH_RETRY_DELAY:-20}"
done

# Alert on the first failure and every 6 hours while it lasts; say so once it recovers.
marker="$OPS_STATE/push-failed"
if [ "$pushed" = 1 ]; then
  if [ -f "$marker" ]; then
    notify "status push recovered: snapshots are reaching crypto-trader-ops again"
    rm -f "$marker"
  fi
  exit 0
fi
if [ ! -f "$marker" ]; then
  date -u +%FT%TZ >"$marker"
  notify "status push to crypto-trader-ops FAILED; scheduled reviews see stale data. Log: $OPS_STATE/push_status.log"
elif [ -n "$(find "$marker" -mmin +360)" ]; then
  notify "status push still failing since $(head -1 "$marker"); log: $OPS_STATE/push_status.log"
  touch "$marker"
fi
exit 1
