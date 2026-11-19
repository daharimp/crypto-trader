# ADR-026: Read-only phone dashboard with bundled TradingView Lightweight Charts

- **Status:** Accepted (owner chose "own dashboard + TradingView charts", phone first, 2026-11-10)
- **Context:** The owner wants to watch the bot from a phone: prices, the strategy's view,
  positions, risk state, and paper perps results. The spec plans a read-only API (BL-041)
  and a dashboard (BL-042).
- **Decision:**
  1. `trader ui serve` runs a stdlib `ThreadingHTTPServer` (no new dependency) that answers
     **GET only**; every other method returns 405. It binds to `127.0.0.1` by default and
     warns when bound elsewhere; reach it from a phone over a VPN or SSH tunnel.
  2. Endpoints: `/api/status` (saved session state and kill switch), `/api/candles`
     (public Kraken OHLC with SMA 20/50), `/api/perps` (paper replay, or the list of
     unapproved values), `/api/prices` (public Jupiter prices). Markets and timeframes come
     from fixed allowlists; static files are served by exact name only.
  3. Charts use TradingView **Lightweight Charts 4.2.0** (Apache-2.0), bundled in
     `src/trader/ui/static/vendor/` with its license, so the page loads no third-party script.
  4. Public Kraken candles are read with a plain HTTPS GET to `/0/public/OHLC` rather than
     ccxt: it needs no client, and ccxt ignores proxy settings in some environments.
  5. A safety test forbids write handlers, control changes, order calls, keys, and file
     writes in `trader/ui/`.
- **Consequences:** The dashboard cannot trade, engage the kill switch, or flatten; owner
  controls stay in the CLI. Adding controls later needs authentication and its own ADR.
  BL-041 is satisfied with the stdlib server instead of FastAPI.
