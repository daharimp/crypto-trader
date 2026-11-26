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
notify() {
  local url kind
  url="$(grep -E '^ALERT_WEBHOOK_URL=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" || true)"
  kind="$(grep -E '^ALERT_WEBHOOK_KIND=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" || true)"
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
# An optional second argument names a function to call before skipping (push_status.sh
# uses it to count skips, so a lock that never frees shows up as an alert).
take_lock() {
  exec 9>"$OPS_STATE/ops.lock"
  if ! flock -w "${1:-0}" 9; then
    echo "another ops script is running; skipping"
    [ -n "${2:-}" ] && "$2" "skipped: another ops script held the lock"
    exit 0
  fi
}

# Failure streaks (ADR-047): alert on the 2nd failure in a row, then once per 24 more
# (hourly scripts: about once a day), and once more when it recovers.
# Reason: one failed hourly push is usually a network blip; a silent streak is not.
streak_fail() {
  local name="$1" msg="$2" f="$OPS_STATE/$1.failures" n=0
  [ -f "$f" ] && n="$(cat "$f" 2>/dev/null || echo 0)"
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  n=$((n + 1))
  echo "$n" >"$f"
  if [ "$n" -ge 2 ] && [ $(((n - 2) % 24)) -eq 0 ]; then
    notify "$name failing $n runs in a row: $msg"
  fi
}

streak_ok() {
  local name="$1" f="$OPS_STATE/$1.failures" n=0
  [ -f "$f" ] && n="$(cat "$f" 2>/dev/null || echo 0)"
  rm -f "$f"
  if [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 2 ]; then
    notify "$name recovered after $n failed runs"
  fi
  return 0
}

# Keep each log under about 1 MB.
trim_log() {
  local f="$OPS_STATE/$1"
  if [ -f "$f" ] && [ "$(wc -c <"$f")" -gt 1000000 ]; then
    tail -c 500000 "$f" >"$f.tmp" && mv "$f.tmp" "$f"
  fi
}
