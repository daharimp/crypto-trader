#!/usr/bin/env bash
# Shared settings for the server ops scripts (ADR-047). Sourced, never run directly.
set -euo pipefail
export PATH="$PATH:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

REPO="${CRYPTO_TRADER_DIR:-$HOME/crypto-trader}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
OPS_STATE="${OPS_STATE_DIR:-$HOME/.local/state/crypto-trader-ops}"
OPS_REPO_DIR="${OPS_REPO_DIR:-$HOME/crypto-trader-ops}"
OPS_REMOTE="${OPS_REMOTE:-git@github-ops:daharimp/crypto-trader-ops.git}"
# Reason: the paper services automation may (re)start. `live` is deliberately absent, so no
# script here can ever start real-money trading.
# shellcheck disable=SC2034  # used by the scripts that source this file
PAPER_SERVICES=(paper perps perps-degen perps-spot-perps review dashboard)

mkdir -p "$OPS_STATE"
cd "$REPO"

# Send one line to the owner's phone through the same webhook the bots use (.env).
# Reason: reads $REPO/.env by full path, because callers may have cd-ed elsewhere.
notify() {
  local url kind
  url="$(grep -E '^ALERT_WEBHOOK_URL=' "$REPO/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" || true)"
  kind="$(grep -E '^ALERT_WEBHOOK_KIND=' "$REPO/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" || true)"
  echo "$(date -u +%FT%TZ) $*"
  [ -n "$url" ] || return 0
  case "${kind:-ntfy}" in
    slack|discord)
      local field=text body
      [ "$kind" = discord ] && field=content
      body="$(printf '%s' "[ops] $*" | python3 -c 'import json,sys;print(json.dumps({sys.argv[1]: sys.stdin.read()}))' "$field")"
      curl -fsS -m 10 -H 'Content-Type: application/json' -d "$body" "$url" >/dev/null || true ;;
    *) curl -fsS -m 10 -d "[ops] $*" "$url" >/dev/null || true ;;
  esac
}

# One ops script at a time, so a health check never runs in the middle of a deploy.
take_lock() {
  exec 9>"$OPS_STATE/ops.lock"
  flock -w "${1:-0}" 9 || { echo "another ops script is running; skipping"; exit 0; }
}

# Keep each log under about 1 MB.
trim_log() {
  local f="$OPS_STATE/$1"
  if [ -f "$f" ] && [ "$(wc -c <"$f")" -gt 1000000 ]; then
    tail -c 500000 "$f" >"$f.tmp" && mv "$f.tmp" "$f"
  fi
}
