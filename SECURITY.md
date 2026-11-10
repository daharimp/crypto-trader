# Security policy

This bot can place real orders on the owner's Kraken account, so security problems are
treated as urgent.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub:
**Security → Report a vulnerability** on this repository (private vulnerability reporting),
or contact the repository owner directly through GitHub. Include what you found, how to
reproduce it, and what an attacker could do with it.

Especially in scope:

- anything that could place, size, or route an order outside the risk engine and execution
  gate, or above the capital cap;
- any path to leverage, margin, short selling, withdrawals, or transfers;
- leaks of API keys or webhook URLs (code, logs, journals, reports, error messages);
- ways to bypass the kill switch, reconciliation, or the live authorization gates.

## If a Kraken API key may be exposed

1. On Kraken, **delete the API key immediately** (this stops all trading through it).
2. On the server: `docker compose run --rm cli killswitch engage --reason "key exposure"`.
3. Check Kraken's order and trade history for activity you don't recognise.
4. Create a new key with the permissions in `docs/operations/RUNBOOK.md` (never
   *Withdraw Funds*), update `.env` on the server, and restart the service.

## Hardening already in place

- Keys are read only from environment variables on the server (`.env`, mode 600) and are
  never written to configs, logs, or the journal. The keys should have no withdrawal
  permission and can be restricted to the server's IP address.
- Spot only: the live adapter can send only an allowlisted set of order parameters.
- Safety tests (`tests/safety/`) scan the source on every CI run.
- Dependencies are locked (`uv.lock`); Dependabot proposes updates, and CI tests them.
