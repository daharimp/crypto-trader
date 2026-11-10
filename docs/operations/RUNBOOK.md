# Runbook: from an empty server to live trading on Kraken

This is the order of operations. Each step has a check. **Do not skip a step to save time:**
every gate exists because the cost of a mistake here is real money.

> Results are not guaranteed. The only strategy so far (`sma_trend`) has been tested on
> synthetic data only. Start live with a small capital cap and raise it only after real
> results justify it.

## 0. Before you start (owner)

- A **Kraken** account that is verified, available in your US state (check Kraken's site),
  and funded with **USD**. Use an account or sub-account that holds **no BTC or ETH** you want
  to keep separate: the bot assumes it is the only thing trading BTC/ETH there and halts if
  balances change underneath it.
- A small always-on **Linux server** (UD-09): 1 vCPU, 1 GB RAM, Ubuntu 24.04 is plenty. Any
  provider works.
- Optional phone alerts: install the free **ntfy** app and pick a long random topic name.

## 1. Server setup (about 15 minutes)

```bash
# on the server, as a normal user with sudo
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER" && newgrp docker
git clone https://github.com/daharimp/crypto-trader.git && cd crypto-trader
git checkout crypto-trader   # until it is merged to main
cp .env.example .env && chmod 600 .env
mkdir -p data && sudo chown 1000:1000 data
docker compose build
docker compose run --rm cli version
```

Check: `version` prints the safety statement.

Optional alerts: put `ALERT_WEBHOOK_URL=https://ntfy.sh/<your-topic>` in `.env`.

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
```

Install Tailscale on the phone, sign in with the same account, and open the printed address.
To stop sharing: `sudo tailscale serve reset`.

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

```yaml
version: 2                       # increment on every change
max_capital_usd: {value: 250, status: approved, ref: UD-22, approved_by: <your name>, approved_on: "YYYY-MM-DD"}
min_paper_cycles_before_live: {value: 6, status: approved, ref: UD-22, approved_by: <your name>, approved_on: "YYYY-MM-DD"}
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

## 8. Changing configuration

Any edit to the profile, risk profile, eligibility, or authorization requires a **version
increment**. A running session detects the change and halts (kill switch). Then:
re-run `profile activate` for the environment, disengage the kill switch, restart the service.

## 9. Emergency without the server

Log in to Kraken, cancel the open orders, and sell manually. The bot will detect the balance
change and halt on its next cycle; reconcile before restarting it.
