# Runbook: from an empty server to live trading on Kraken

This is the order of operations. Each step has a check. **Do not skip a step to save time:**
every gate exists because the cost of a mistake here is real money.

> Results are not guaranteed. The only strategy so far (`sma_trend`) has been tested on
> synthetic data only. Start live with a small capital cap and raise it only after real
> results justify it.

## 0. Before you start (owner)

- A **Kraken** account that is verified, available in your US state (check Kraken's site),
  and funded with **USD**. Use a separate account or sub-account holding **only USD**: the
  bot trades BTC, ETH, SOL, XRP, and SUI, assumes it is the only thing trading them there,
  and halts if balances change underneath it.
- A small always-on **Linux server** (UD-09): 1 vCPU, 1 GB RAM, Ubuntu 24.04 is plenty. Any
  provider works.
- Optional phone alerts: install the free **ntfy** app and pick a long random topic name.

## 1. Server setup (about 15 minutes)

```bash
# on the server, as a normal user with sudo
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER" && newgrp docker
# The repository is private: give the server a read-only deploy key.
ssh-keygen -t ed25519 -N "" -f ~/.ssh/crypto_trader_deploy -C "crypto-trader server"
cat ~/.ssh/crypto_trader_deploy.pub
# On GitHub: repo Settings -> Deploy keys -> Add deploy key -> paste it; leave
# "Allow write access" UNTICKED.
printf 'Host github.com\n  IdentityFile ~/.ssh/crypto_trader_deploy\n' >> ~/.ssh/config
git clone git@github.com:daharimp/crypto-trader.git && cd crypto-trader
git checkout crypto-trader   # until it is merged to main
cp .env.example .env && chmod 600 .env
mkdir -p data && sudo chown 1000:1000 data
docker compose build                 # one image, crypto-trader:local, for every service
docker compose run --rm cli version
```

Check: `version` prints the safety statement.

All services (paper, perps, dashboard, live, cli, builder) run the same image, and
`docker compose build` is the only command that refreshes it (ADR-036). If a command answers
`No such image: crypto-trader:local`, run `docker compose build` first.

Run every `docker compose` command from inside the project folder (`cd ~/crypto-trader`).
If Docker answers:

- `no configuration file provided`: you are not in `~/crypto-trader`.
- `unknown flag: --rm` (or `--tail`): Docker did not see the word `compose`. Retype the
  command by hand (copying from a phone or chat app can swap the space for an invisible
  character) and check that `docker compose version` prints a version.

Optional alerts: put `ALERT_WEBHOOK_URL=https://ntfy.sh/<your-topic>` in `.env`.

## 1a. Build your own profile (optional)

Answer one question per risk setting, either in the terminal or with the web form
(`docs/profile-builder/index.html`, then save its answers as `answers.json` on the server):

```bash
mkdir -p docs/profiles && sudo chown 1000:1000 configs/profiles configs/risk docs/profiles
docker compose run --rm builder                                    # terminal interview
docker compose run --rm -v ./answers.json:/app/answers.json:ro builder --answers answers.json
```

Only the `builder` service can write `configs/`; the bot services keep it read-only.

It writes `configs/profiles/<name>.yaml`, `configs/risk/<name>.yaml`, and a spec sheet in
`docs/profiles/`. Use `configs/profiles/<name>.yaml` instead of `balanced-paper.yaml` in the
steps below and set `TRADER_PROFILE=configs/profiles/<name>.yaml` in `.env` so the `paper` and
`live` services run it.

## 1b. Server that already runs n8n (or other apps)

The bot runs beside n8n without touching it: its own folder, its own compose project
(`crypto-trader`), no shared ports or volumes. Check the server first:

```bash
uname -a; lsb_release -a; free -h; df -h /
docker --version; docker compose version
docker ps --format '{{.Names}}  {{.Ports}}'
```

Need: Linux, at least 1 GB RAM free with n8n running, 5 GB disk free, Docker with compose v2,
and nothing already using port 8787. If Docker is already installed for n8n, **skip the
`get.docker.com` line** in step 1 and do the rest. Never run `docker compose down` from the
n8n folder for the bot, or from the bot folder for n8n.

## 1c. Phone alerts with ntfy

Install the free **ntfy** app, subscribe to a long random topic name (it acts as a password),
then on the server:

```bash
nano .env      # ALERT_WEBHOOK_URL=https://ntfy.sh/<your-topic>   ALERT_WEBHOOK_KIND=ntfy
curl -d "trader alert test" "ntfy.sh/<your-topic>"     # should arrive on the phone
```

## 2. Start paper trading on live Kraken prices (starts the track record)

```bash
docker compose run --rm cli profile activate configs/profiles/balanced-paper.yaml \
  --environment paper --reason "start paper track record"
docker compose up -d paper dashboard
docker compose logs -f paper        # Ctrl-C to stop watching; the session keeps running
docker compose run --rm cli session status
```

Check: `session status` shows a `last bar` that advances every 4 hours (00, 04, 08, 12, 16,
20 UTC, about 2 minutes after the hour). Each completed bar counts toward the paper track
record that live trading requires.

## 2b. Dashboard on your phone with Tailscale

The dashboard is read-only and listens on the server's `127.0.0.1:8787` only. Tailscale makes
it reachable from your own devices and nobody else's.

```bash
docker compose up -d dashboard
curl -s http://127.0.0.1:8787/api/status          # JSON means it is running
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                                  # log in with the same account as your phone
sudo tailscale serve --bg 8787                     # prints https://<server>.<tailnet>.ts.net
tailscale serve status                             # shows that address again any time
```

1. If `serve` answers **"Serve is not enabled on your tailnet"** with a link: open the link,
   log in, click **Enable** (also turn on **HTTPS certificates** and **MagicDNS** if offered),
   then run `sudo tailscale serve --bg 8787` again.
2. On **every device** that should see the dashboard (phone, laptop): install Tailscale, sign
   in with the same account, and keep it switched on. `tailscale status` on the server lists
   each connected device.
3. Open the printed `https://<server>.<tailnet>.ts.net` address: `https`, no port number. The
   first load can take a minute while Tailscale issues the certificate. The server's own
   Tailscale IP with `:8787` does not work: the dashboard listens on the server only.

If the browser says the site **can't be reached** (`DNS_PROBE_FINISHED_NXDOMAIN`), that device
is not connected to your Tailscale account, or Chrome's secure DNS is skipping Tailscale's
names: turn off Chrome → Settings → Privacy and security → Security → **Use secure DNS**, or
try Safari. `--bg` keeps the setting across restarts. To stop sharing:
`sudo tailscale serve reset`.

If the page **stops loading** but other sites work: check that Tailscale is on and
connected on that device (menu bar icon on a Mac; it can disconnect after sleep), then
reload. On the server, `bash scripts/ops/dashboard_check.sh` probes the page, restarts only
the dashboard if it does not answer, and alerts your phone; it runs every 5 minutes and with
each watchdog run (ADR-050). `cat data/ops/dashboard.txt` shows its last result.

The page refreshes itself every 60 seconds and is never cached. Prices move every minute;
equity, positions, and trades change when the bots run, every 4 hours.

## 2c. Leverage practice: paper perps, long and short (ADR-031)

This runs beside the spot paper bot with its own simulated $2,500. It goes long in uptrends
and short in downtrends at the leverage limits you approved (UD-23). It has no keys and
cannot place a real order.

```bash
docker compose up -d perps
docker compose run --rm cli perps paper status
docker compose logs --tail 20 perps
```

If `status` answers `No such command 'paper'`, the image is older than the code: run the
update in section 8a.

Check: `status` shows equity, any open long or short positions, and `bars processed` rising
by one every 4 hours. The dashboard opens on the same account (**Leverage · paper**): slide between
Overview, Positions, Trades and Markets to see its value, each open long or short with its
leverage and liquidation price, and every closed trade with dollars won or lost (ADR-037). Opens, closes, and liquidations arrive as phone alerts starting with
`[perps paper]`. The emergency stop (`trader killswitch engage`) blocks new paper positions
here too.

Every position has a stop-loss (ADR-042): it closes once it has lost 50% of its collateral,
fees included, which is about 2 typical daily moves from entry and about half way to its
liquidation price. That market then waits for the next UTC day before opening again. Change
it in `configs/perps/jupiter.yaml` (`stop_loss_pct_of_collateral`, raise `version`, update
`approved_on`, then `docker compose restart perps`); a file without a stop refuses to start
(exit 3), on every account.

The session follows the 1-month trend rule (`tsmom_30d`: long if the price is above its level
30 days ago, short if below; ADR-035). To run a different rule add
`--signal consensus_sma_tsmom` or `--signal sma_stance_20_50` to the `perps` command
in `docker-compose.yml`. A saved account will not continue under a different rule, so when you
switch, archive the old run and start a new one (ADR-041):

```bash
docker compose stop perps
docker compose run --rm cli perps paper reset --reason "switching to consensus_sma_tsmom"
docker compose up -d perps
docker compose run --rm cli perps paper runs        # every past run, with its result
```

`reset` never deletes anything. It moves the run's state, trades and per-bar equity curve
into `data/archive/perps/perps-paper/<start>__<end>/` and writes a `summary.json` there
(start and final equity, P&L, peak, largest drop, trades, stops, liquidations, fees, settings
and your reason). The new run then starts with empty logs, so the dashboard shows only the
current run. `runs` also lists any older `data/state/perps-paper-<date>.json` files moved
aside by hand before this existed (their start, final and peak equity, without a curve).
Always stop the account before `reset`; if you forget, the running session notices the
archive, sends an alert and exits instead of writing the old run back, and Docker restarts it
into a fresh run.

## 2d. Second paper account with its own settings ("degen", ADR-038)

A separate paper perps account beside the one in 2c, with its own simulated $2,500, its own
settings (`configs/perps/jupiter-degen.yaml`) and its own record
(`data/state/perps-degen.json`). Starting, stopping or resetting it never touches `perps`.
It has no keys and cannot place a real order.

```bash
git pull && docker compose build                     # section 8a, if the image is older
docker compose run --rm cli perps validate --account degen
docker compose up -d perps-degen
docker compose run --rm cli perps paper status --account degen
docker compose logs --tail 20 perps-degen
```

Check: `validate` lists 5% collateral, buffer 3, stop 30% of collateral and the 15% daily
limit; `status` shows `bars processed` rising every hour: this account checks every hour,
taking its 30-day trend and volatility from 4-hour candles (ADR-040). On the dashboard, tap
**Degen · paper**; its Overview also lists the settings in force. Tap **All** to see every
account's open positions together, with entry, price now, liquidation or stop on each card. Alerts start with
`[perps degen]`. A **BAD DAY** alert means the account lost 15% since 00:00 UTC (7pm New York
in winter): it opens nothing new until 00:00 UTC; look at what happened before the next day.

If this account already ran with 4-hour checks, the hourly version refuses that saved record
(`perps session not started: ... different signal, timeframe`): keep it and start fresh with
the three commands at the end of this section, then `docker compose up -d perps-degen`.

To check the main account every hour too, only after its 7-day test: add
`"--timeframe", "1h"` to the `perps` command in `docker-compose.yml`, then reset it as in 2c.

To change a setting: edit its `value` in `configs/perps/jupiter-degen.yaml`, raise `version`
by one, set `approved_on` to today, then `docker compose restart perps-degen`. Run
`perps validate --account degen` first; a `TBD` or out-of-range value stops the account
(exit 3 or 2) instead of guessing. A new buffer or collateral applies to new positions only.
To start this account over, archive the old run (ADR-041, as in 2c):

```bash
docker compose stop perps-degen
docker compose run --rm cli perps paper reset --account degen --reason "why it ends"
docker compose up -d perps-degen
```

## 2e. Long and short on every bot, and the spot-perps account (ADR-044)

Every perps account now picks its side from one shared trend rule
(`trader/regimes/trend.py`): long while the 50-candle average of 4h closes (about 8 days)
is above the 200-candle average (about 33 days), short while it is below. When the last 30
days have been choppy (efficiency ratio below 0.05) the faster 10/30-candle averages decide
instead, so expect more trades in sideways markets. Spot code stays
long-only, so spot's rule also runs both ways in a third paper account, `spot-perps`, at 1x
(`configs/perps/jupiter-spot-perps.yaml`).

Switching an existing account to the new rule needs its old run archived first (a saved run
with a different signal refuses to resume). Once, after pulling this change:

```bash
docker compose build
docker compose stop perps perps-degen
docker compose run --rm cli perps paper reset --account main --reason "switch to shared trend rule long/short (ADR-044)"
docker compose run --rm cli perps paper reset --account degen --reason "switch to shared trend rule long/short (ADR-044)"
docker compose run --rm cli perps validate --account spot-perps
docker compose up -d perps perps-degen perps-spot-perps
docker compose run --rm cli perps paper status --account spot-perps
```

Alerts from the new account start with `[spot perps]`. It always runs the shared rule;
`--signal` with anything else exits 2.

## 2f. Ten coins, hourly, small positions: the top10 account (ADR-051)

A fourth paper perps account beside the others, with its own simulated $2,500, its own
settings (`configs/perps/top10.yaml`) and its own record (`data/state/perps-top10.json`).
It runs the shared trend rule on BTC, ETH, BNB, XRP, SOL, TRX, HYPE, ZEC, DOGE and LINK,
decides every hour (the trend still comes from 4-hour candles), and posts 1% of the account
per position at 5x or less, so a stopped trade costs about 0.3% of the account. It models no
exchange, has no keys and cannot place a real order. Starting, stopping or resetting it
never touches the other accounts.

With auto-deploy (8b) it starts by itself: the deploy that brings this code restarts the
existing bots, and the next watchdog run (within 15 minutes) creates the new service and
sends `[ops] started the new service perps-top10`. By hand:

```bash
git pull && docker compose build                     # section 8a, if the image is older
docker compose run --rm cli perps validate --account top10
docker compose up -d perps-top10
docker compose run --rm cli perps paper status --account top10
docker compose logs --tail 20 perps-top10
```

Check: `validate` lists 1% collateral, buffer 8, stop 30% of collateral, the 15% daily limit
and the 4R/8R/12R ladder; `status` shows `bars processed` rising every hour, about four
minutes after the hour (it waits for the other accounts' price requests to finish and spaces
its own twenty a second apart). Alerts start with `[perps top10]`; expect about 8 to 10 a day.
It always runs on 1h: `--timeframe 4h` exits 2. The dashboard does not show this account yet;
use `status`, the alerts, or the hourly snapshot in `crypto-trader-ops`.

If one coin's prices cannot be read, the whole account waits and alerts once
(`cycle failed, will retry`), then says when prices are back. To drop or swap a coin: edit
`markets` in `configs/perps/top10.yaml`, raise `version`, then archive the run and restart
(a saved run with a different coin list refuses to resume):

```bash
docker compose stop perps-top10
docker compose run --rm cli perps paper reset --account top10 --reason "why it ends"
docker compose up -d perps-top10
```

A coin needs a Kraken pair in `_KRAKEN_PAIRS` (`src/trader/ui/data.py`); without one the
account refuses to start (exit 2) and names the coin. To change a setting, follow 2d with
`--account top10` and `perps-top10`.

## 3. Create the Kraken API key (owner, on kraken.com)

Kraken Pro → Settings → API → Create key. Grant **only**:

- Query Funds
- Query Open Orders & Trades
- Query Closed Orders & Trades
- Create & Modify Orders
- Cancel/Close Orders

**Never grant Withdraw Funds.** (Permission names can differ slightly in Kraken's UI.) If
offered, restrict the key to your server's IP address. Put the key and secret into `.env` on
the server only:

```bash
nano .env        # KRAKEN_API_KEY=...  KRAKEN_API_SECRET=...
```

Never commit `.env`, email it, or paste keys into a chat.

## 4. Preflight (checks everything, places no orders)

```bash
docker compose run --rm cli live preflight --profile configs/profiles/balanced-paper.yaml
```

It checks the clock, Kraken's minimum order sizes, the balance query, that the account holds
no BTC/ETH, and asks Kraken to **validate** (not place) a market buy and a stop-loss order.
Every line must be `PASS`. The last line reminds you to confirm by hand that the key cannot
withdraw.

## 5. Authorize live trading (owner decision UD-22)

Edit `configs/live/authorization.yaml` on the server:

Already set by the owner on 2026-11-02 (UD-22): $250 cap and 42 paper cycles. What remains
is the **acknowledgement in your own words**, with a version increment:

```yaml
version: 3                       # increment on every change
max_capital_usd: {value: 250, status: approved, ref: UD-22, approved_by: <your name>, approved_on: "YYYY-MM-DD"}
min_paper_cycles_before_live: {value: 42, status: approved, ref: UD-22, approved_by: <your name>, approved_on: "YYYY-MM-DD"}
acknowledgement:
  acknowledged_by: <your name>
  acknowledged_at_utc: "YYYY-MM-DDTHH:MM:SSZ"
  statement: "<in your own words: you accept that real money can be lost and nothing is guaranteed>"
```

- `max_capital_usd`: the most the bot may manage even if the account holds more.
  Recommendation: **$100–250** for the first weeks.
- `min_paper_cycles_before_live`: completed 4h paper bars required first.
  Recommendation: at least **6** (one day). More is better.

Check: `docker compose run --rm cli profile validate configs/profiles/balanced-paper.yaml
--environment live` lists only the missing activation (and the paper count, if not reached).

## 6. Go live

```bash
docker compose run --rm cli profile activate configs/profiles/balanced-paper.yaml \
  --environment live --reason "go live with $250 cap"
docker compose stop paper
docker compose --profile live up -d live
docker compose logs -f live
```

On first start the bot requires the account to hold no BTC/ETH and sets its managed cash to
`min(USD balance, max_capital_usd)`. After every buy it places a **stop-loss order at
Kraken**, so the position stays protected even if the server goes down.

## 7. Daily operation

| Task | Command |
|---|---|
| Status | `docker compose run --rm cli session status` |
| Logs | `docker compose logs --tail 200 live` |
| **Stop new orders** (positions and stops stay) | `docker compose run --rm cli killswitch engage --reason "..."` |
| Resume | `docker compose run --rm cli killswitch disengage --reason "..."` |
| **Sell everything now** (works with the kill switch on) | `docker compose run --rm cli session flatten --reason "..."` |
| Reset a tripped drawdown breaker | `docker compose run --rm cli session reset-breaker --reason "..."` |
| Stop the bot | `docker compose stop live` |
| Verify a journal | `docker compose run --rm cli journal verify <run_id>` |

The bot halts itself (kill switch) on any of these: balances at Kraken differ from its ledger,
a protective stop disappears, the clock drifts more than 5 s from Kraken's, market data is stale
for 3 bars, 3 consecutive exchange errors, the configuration changes while running, or any
unexpected error. Investigate, fix, then disengage the kill switch.

## 7a. AI review assistant for the paper accounts (ADR-039)

> **Now (ADR-048, 2026-11-23): the server makes no AI calls.** `server_ai_reviews: false` in
> `configs/assistant.yaml` keeps the `review` service to the code-only drawdown alerts (no
> API key needed). The daily scheduled review on your Claude plan writes the daily summary
> and a review of each trade closed that day to `reviews/` in the private
> `crypto-trader-ops` repo, shortly after the status push at 00:20 UTC. Set it back to
> `true` (with an API key in `.env`) to bring the server reviews below back.
>
> **Per-trade reviews on a free model (ADR-049).** The `review` service also asks a free
> OpenRouter model to review each paper trade soon after it closes, and saves it in
> `data/reports/trades/<account>/` (Markdown, plus JSON with the raw facts). One-time setup:
> create a key at openrouter.ai, and in its privacy settings allow free endpoints that may
> train on inputs (the prompts hold only simulated trade numbers). Then on the server:
>
> ```bash
> nano .env                     # add: OPENROUTER_API_KEY=<your key>
> docker compose up -d review   # recreate the container so it picks up the key
> docker compose logs --tail 5 review   # "free per-trade reviews: on, models [...]"
> ```
>
> Without the key it skips quietly. Models and the daily call budget are in
> `configs/assistant.yaml` under `free_trade_reviews` (raise `daily_call_budget` after a
> one-time $10 OpenRouter credit purchase lifts the free cap from 50 to 1,000 a day).

When a paper perps account has a bad day (it lost the daily limit and stopped for the rest of
the UTC day), the review assistant reads that account's record, settings and the market, and
six AI reviewers each do one job: market analyst, trade reviewer and risk officer (each on its
own, from the same measured facts), then a strategy researcher proposes at most three setting
changes, a skeptic challenges each, and a lead editor writes you a plain-language report.
Every proposed value is checked by code against the account's config rules. **It cannot change
anything**: you decide, and you edit the settings file yourself (RUNBOOK 2d for the degen
account, section 8 for others).

One-time setup: create an API key at console.anthropic.com and add one line to `.env` on the
server (never in the repository, a config file, or chat):

```bash
nano .env                     # add: ANTHROPIC_API_KEY=<your key>
docker compose up -d review   # watches both paper accounts for bad days
docker compose logs --tail 20 review
```

Ask for a review any time, and read reports:

```bash
docker compose run --rm cli review run --account main --dry-run   # the facts only, free
docker compose run --rm cli review run --account main             # full review (uses the API)
docker compose run --rm cli review show --account main            # newest report
```

Reports are saved in `data/reports/review-<account>-<day>.md` (and `.json` with the facts).
A phone alert starting `[review]` tells you when one is ready. Each review makes six requests
to Claude (`configs/assistant.yaml` sets the model and effort per role); expect cents to well
under a dollar per review, billed to your Anthropic account. Without a key the commands exit 3
and the trading bots are unaffected. AI reviewers can be wrong; one day is a small sample.

**Every trade, every day (ADR-046).** Shortly after 00:00 UTC the same `review` service makes one
request that writes a summary of main, degen, spot-perps, top10 and spot and reviews every
trade they closed that day, and it alerts when an account falls 5, 10 or 15 % below its peak. Turn any
of these off, or change the accounts and levels, in `configs/assistant.yaml`, then
`docker compose up -d --force-recreate review`.

```bash
docker compose run --rm cli review trade --account degen --last 3   # one request per trade, now
docker compose run --rm cli review daily --day 2026-11-22           # summary for one day
docker compose run --rm cli review show --daily                     # newest daily summary
```

Daily reports (with every trade): `data/reports/daily-<day>.md`; on-demand trade reviews:
`data/reports/trades/<account>/`.

## 8. Changing configuration

Any edit to the profile, risk profile, eligibility, or authorization requires a **version
increment**. A running session detects the change and halts (kill switch). Then:
re-run `profile activate` for the environment, disengage the kill switch, restart the service.

## 8a. Updating the code

```bash
docker compose run --rm cli killswitch engage --reason "update"   # positions and stops stay
git pull
docker compose build                  # rebuilds the one image every service uses
docker compose up -d paper perps dashboard
#   when live: docker compose --profile live up -d live perps dashboard
docker compose ps --format '{{.Service}} {{.Image}}'   # every line shows the same image ID
docker image inspect crypto-trader:local --format '{{.Id}}'   # that same ID
docker compose run --rm cli session status
docker compose run --rm cli killswitch disengage --reason "update done"
```

`docker compose build` builds one image, `crypto-trader:local`, and every service runs it,
including `cli`, `builder`, and `live`, which sit behind profiles (ADR-036). So these steps
cannot leave one of them on old code. `up -d` restarts each running service on the new image;
a service you do not name keeps running the old code until you restart it.

**Once, after the update that brought ADR-036 (2026-11-14):** the old layout gave each
service its own image (`crypto-trader-paper`, `crypto-trader-cli`, ...). After the steps
above, remove them to free disk space:

```bash
docker image ls 'crypto-trader-*'
docker image rm crypto-trader-paper crypto-trader-perps crypto-trader-dashboard \
  crypto-trader-cli crypto-trader-builder crypto-trader-live
```

`No such image` for a name you never built is fine. `image is being used by ... container`
means a container still points at it: `docker ps -a --filter ancestor=<image>` shows which.
If it is running, restart that service on the new image first (`up -d <service>`, with
`--profile live` for live); if it is stopped, `docker rm <container id>`, then remove the
image again. Leaving old images in place is harmless; they only use disk.

If the update changed a profile, risk, eligibility, or authorization file, re-run
`profile activate` first (section 8). Read `CHANGELOG.md` before updating a live bot.

## 8b. Hands-off: auto-deploy, watchdog and status push (ADR-047)

Once set up, merging to `main` deploys itself, the server checks the bots every 15 minutes
and alerts your phone only when something is wrong, and scheduled reviews read the bots'
status without logging in to the server.

1. On GitHub, create an **empty private** repository named `crypto-trader-ops` (no README).
2. On the server, after a `git pull` that brings this section:

   ```bash
   cd ~/crypto-trader && bash scripts/ops/install.sh
   ```

   It builds the image (running bots are not restarted), installs three cron jobs
   (auto-deploy every 5 minutes, watchdog every 15, status push hourly at :20) and prints a
   new public key. Auto-deploy starts **on hold**: release it with
   `bash scripts/ops/hold.sh off` once the current main is fine to deploy (if main needs an
   archive and reset of paper runs first, do that before releasing).
3. In `crypto-trader-ops` -> Settings -> Deploy keys -> Add deploy key, paste that key and
   **tick "Allow write access"**. This key works only for the ops repository; the server's
   key for the bot code stays read-only.
4. Check: `bash scripts/ops/watchdog.sh` prints `OK` or a list of findings, and
   `bash scripts/ops/push_status.sh` makes the first commit in `crypto-trader-ops`.

Alerts use the same `ALERT_WEBHOOK_URL` as the bots (section 1c), prefixed `[ops]` for
deploys and `[watchdog]` for health problems. Logs are in `~/.local/state/crypto-trader-ops/`.

Auto-deploy restarts only `paper perps perps-degen perps-spot-perps perps-top10 review
dashboard`; it never starts `live`. A service that a deploy adds is created by the next
watchdog run (`scripts/ops/start_new.sh`, ADR-051), because the deploy reads its service
list before it pulls; that script never builds, never touches an existing container, and
does nothing after `docker compose down`. It skips, and alerts once, if files were edited on the server
(`git status`) or the server is not on `main`. A failed build rolls back to the previous
commit. Pause it before merging something that needs a reset first:
`bash scripts/ops/hold.sh on "reason"`; `hold.sh off` releases it and `hold.sh` shows the
state. While held it alerts once per waiting commit. To remove all of
it: delete the `crypto-trader-ops` block in `crontab -e`.

## 9. Emergency without the server

Log in to Kraken, cancel the open orders, and sell manually. The bot will detect the balance
change and halt on its next cycle; reconcile before restarting it.
