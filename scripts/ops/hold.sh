#!/usr/bin/env bash
# Pause or release auto-deploy (ADR-047).
#   bash scripts/ops/hold.sh on "reason"   # pause; running bots are untouched
#   bash scripts/ops/hold.sh off           # release; the next 5-minute run deploys main
#   bash scripts/ops/hold.sh               # show the current state
source "$(dirname "$0")/common.sh"
case "${1:-status}" in
  on) echo "${2:-paused by owner}" >"$OPS_STATE/deploy-hold"; echo "auto-deploy on hold" ;;
  off) rm -f "$OPS_STATE/deploy-hold" "$OPS_STATE"/skip-*; echo "auto-deploy released" ;;
  *) if [ -f "$OPS_STATE/deploy-hold" ]; then echo "on hold: $(cat "$OPS_STATE/deploy-hold")"; else echo "auto-deploy active"; fi ;;
esac
