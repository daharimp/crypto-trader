# ADR-047: Hands-off operations: auto-deploy, a server watchdog, and a status push

- **Status:** Accepted (2026-11-22; owner request in the project thread: "scheduled
  monitoring ... lets also act on this")
- **Context:** Every deploy and every look at the paper bots went through the owner's
  MacBook (Remote Control plus SSH), which often blocks SSH and needs the Mac to be awake.
  The owner wants the bots monitored every few hours and reviewed daily without that.
  Scheduled Claude tasks run in cloud containers that cannot (and should not) log in to the
  trading server.
- **Decision:**
  1. **Auto-deploy** (`scripts/ops/autodeploy.sh`, cron every 5 minutes). When `origin/main`
     moves it fast-forwards, runs `docker compose build`, restarts only the paper services
     (`paper perps perps-degen perps-spot-perps review dashboard`) and sends one alert. It
     never names `live`, so automation can never start real-money trading. It skips (and
     alerts once per commit) when the server is on another branch, has edited tracked files,
     or main was rewritten. A failed build rolls back to the previous commit and that commit
     is not retried until main moves again. It uses the existing read-only deploy key. It compares
     `origin/main` with the commit last deployed (not the checkout), so a manual `git pull`
     still gets deployed. A **hold** (`scripts/ops/hold.sh on|off`) pauses it so a deploy that
     needs an approved archive and reset of paper runs waits for the owner; the first install
     starts on hold.
  2. **Watchdog** (`scripts/ops/watchdog.sh`, every 15 minutes) saves `docker compose ps` and
     the last 20 minutes of logs to `data/ops/`, then runs `trader ops health --alert` in the
     `cli` container. The checks are read-only: expected containers running (and a warning if
     `live` runs), error lines per service, spot sessions fresh with a stop on every position
     and breaker closed, every perps config resolving a stop-loss, perps accounts fresh, and
     drawdown from peak at the review assistant's 5/10/15% steps (ADR-046). Alerts are
     de-duplicated: a problem alerts when new, when its severity rises, every 12 hours while
     it lasts, and once when it clears. If the check itself cannot run, the script alerts at
     most once an hour. The result is saved as `data/ops/health.json`.
  3. **Status push** (`scripts/ops/push_status.sh`, hourly at :20) copies `health.json`,
     `data/reports/`, `data/state/*.json`, `data/logs/*.jsonl` and the deployed commit to a
     separate private repository, `daharimp/crypto-trader-ops`, with its own write deploy key
     (SSH host alias `github-ops`). That key can write only to the ops repository, so the
     server still cannot change the bot code. Secrets never live under `data/` (`.env` holds
     them), so none are pushed.
  4. **Scheduled reviews** (Claude scheduled tasks, outside this repository) read the ops
     repository: a 4-hourly check that also treats a `health.json` older than 2 hours as the
     server going quiet, and a daily review after the end-of-day report that may open tuning
     pull requests backed by backtests. Strategy and risk changes still go only through
     reviewed, tested pull requests (no live self-modification), and anything that resets a
     paper run or touches live trading still needs the owner.
- **Alternatives rejected:** giving the cloud an SSH key to the server (a cloud secret
  would be a shell on the trading box); a write deploy key on the code repository (with
  auto-deploy, a compromised server could push code that then deploys itself); relying on
  the Mac (the problem being solved).
- **Consequences:** merging to main deploys within about 5 minutes, so main must stay
  deployable (CI runs on every pull request). One-time setup is `scripts/ops/install.sh` on
  the server plus adding its printed key to the ops repository (RUNBOOK 8b).
- **Amendment (2026-11-26, status push outage):** from Nov 24 00:43 UTC every hourly push was
  rejected as non-fast-forward for about 48 hours. The daily review commits `reviews/` to
  the ops repository, and `push_status.sh` ran `git pull --rebase` while the fresh snapshot
  was still uncommitted, so git refused, the error was hidden, and the push then failed.
  Now the script commits first, fetches, rebases onto `origin/main` (falling back to a
  merge with `-X ours`, so remote commits such as `reviews/` are always kept and the
  server's newer snapshot wins inside its own files), retries once, and never force-pushes.
  A failed push alerts the phone on the first failure, every 6 hours while it lasts, and
  once on recovery (marker `$OPS_STATE/push-failed`). `notify` now reads `$REPO/.env` by
  full path so it works after a script changes directory.
