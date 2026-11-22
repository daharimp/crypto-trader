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

cd "$dest"
git add -A
git -c user.name="crypto-trader server" -c user.email="ops@localhost" \
  commit --quiet -m "status $(date -u +%FT%TZ)" || exit 0
git push --quiet origin HEAD:main
