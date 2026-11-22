#!/usr/bin/env bash
# Auto-deploy (ADR-047): when origin/main moves, fast-forward, rebuild, restart the paper bots.
# Skips (and alerts once) if the server has local edits; rolls back if the build fails.
source "$(dirname "$0")/common.sh"
take_lock 0
trim_log autodeploy.log

git fetch --quiet origin "$DEPLOY_BRANCH"
local_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse "origin/$DEPLOY_BRANCH")"
# Reason: compare with the commit the bots were last deployed on, not the checkout, so a
# manual `git pull` (which restarts nothing) still gets built and deployed.
deployed_sha="$(cat "$OPS_STATE/deployed-sha" 2>/dev/null || true)"
[ "$deployed_sha" = "$remote_sha" ] && exit 0

# Alert once per target commit, not every 5 minutes.
once() {
  local marker="$OPS_STATE/skip-$remote_sha"
  [ -f "$marker" ] && exit 0
  touch "$marker"
  notify "$1"
  exit 0
}

# Reason: a hold lets the owner approve a deploy first (for example one that archives and
# resets paper runs). install.sh starts on hold; `scripts/ops/hold.sh off` releases it.
if [ -f "$OPS_STATE/deploy-hold" ]; then
  once "auto-deploy on hold ($(head -1 "$OPS_STATE/deploy-hold")); $(git log -1 --format='%h %s' "$remote_sha") is waiting. Release: bash scripts/ops/hold.sh off"
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "$DEPLOY_BRANCH" ] || once "auto-deploy skipped: server is on branch $branch, not $DEPLOY_BRANCH"
[ -z "$(git status --porcelain --untracked-files=no)" ] || \
  once "auto-deploy skipped: files were edited on the server (git status). Commit or discard them."
[ -f "$OPS_STATE/failed-$remote_sha" ] && exit 0
git merge-base --is-ancestor "$local_sha" "$remote_sha" || \
  once "auto-deploy skipped: main was rewritten; needs a manual pull"

[ "$local_sha" = "$remote_sha" ] || git merge --ff-only --quiet "origin/$DEPLOY_BRANCH"
subject="$(git log -1 --format='%h %s')"
if docker compose build --quiet && docker compose up -d "${PAPER_SERVICES[@]}"; then
  echo "$remote_sha" >"$OPS_STATE/deployed-sha"
  notify "deployed $subject"
  rm -f "$OPS_STATE"/skip-* "$OPS_STATE"/failed-*
else
  touch "$OPS_STATE/failed-$remote_sha"
  git reset --quiet --hard "$local_sha"
  docker compose build --quiet && docker compose up -d "${PAPER_SERVICES[@]}" || true
  notify "deploy of $subject FAILED; rolled back to $(git log -1 --format='%h'). It will retry when main changes."
  exit 1
fi
