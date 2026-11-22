#!/usr/bin/env bash
# One-time setup for auto-deploy, the watchdog and the status push (ADR-047).
# Safe to re-run: it replaces only its own crontab block and never overwrites a key.
source "$(dirname "$0")/common.sh"
chmod +x "$REPO"/scripts/ops/*.sh
mkdir -p data/ops && chmod 0777 data/ops  # the cli container (uid 1000) writes here too

key="$HOME/.ssh/crypto_trader_ops"
if [ ! -f "$key" ]; then
  ssh-keygen -q -t ed25519 -N "" -f "$key" -C "crypto-trader server status push"
fi
if ! grep -q "^Host github-ops" "$HOME/.ssh/config" 2>/dev/null; then
  printf '\nHost github-ops\n  HostName github.com\n  User git\n  IdentityFile %s\n  IdentitiesOnly yes\n' \
    "$key" >>"$HOME/.ssh/config"
  chmod 600 "$HOME/.ssh/config"
fi

scripts="$REPO/scripts/ops"
block="# BEGIN crypto-trader-ops (ADR-047)
CRYPTO_TRADER_DIR=$REPO
*/5 * * * * $scripts/autodeploy.sh >>$OPS_STATE/autodeploy.log 2>&1
2-59/15 * * * * $scripts/watchdog.sh >>$OPS_STATE/watchdog.log 2>&1
20 * * * * $scripts/push_status.sh >>$OPS_STATE/push_status.log 2>&1
# END crypto-trader-ops"
{ crontab -l 2>/dev/null | sed '/# BEGIN crypto-trader-ops/,/# END crypto-trader-ops/d'; echo "$block"; } | crontab -

echo "Installed. Cron jobs:"
crontab -l | sed -n '/# BEGIN crypto-trader-ops/,/# END crypto-trader-ops/p'
echo
echo "Add this key to github.com/daharimp/crypto-trader-ops -> Settings -> Deploy keys,"
echo "with 'Allow write access' TICKED (it can write only to that repo):"
cat "$key.pub"
