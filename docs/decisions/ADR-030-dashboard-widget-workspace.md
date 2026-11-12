# ADR-030: Dashboard as a draggable widget workspace

- **Status:** Accepted (2026-11-12; owner asked for "a seamless dashboard experience, more of
  a drag and open/interact type of experience", viewable on a computer as well as a phone)
- **Context:** The ADR-026 dashboard is one fixed column built for a phone. On a computer it
  wastes the screen, it shows only three of the five universe coins, and nothing on it can be
  rearranged or opened for detail.
- **Decision:**
  1. The page is a workspace of seven widgets (account, bot health, chart, markets, positions,
     closed trades, leverage-practice replay) on a 12-column grid: one column on a phone, two
     on a tablet, 4/6/8/12-column spans on a desktop.
  2. **Move:** drag a widget by its grip (touch and mouse) or its header (mouse); arrow keys
     on the grip do the same. **Resize:** drag a widget's right edge on a desktop, or use the
     arrow keys on it. **Open:** tap a widget's title to grow the same card into a sheet with
     its detail table; Escape, the close button, or the backdrop closes it. **Show/hide and
     reset:** the Layout menu. A market row opens that coin on the chart.
  3. The layout is saved in the browser's `localStorage` only. Nothing is sent to the server.
  4. The server stays **GET only** (ADR-026). New read-only pieces: `/api/watch` (price, 24h
     change, the `sma_trend` stance, 7-day sparkline per coin), XRP and SUI added to the fixed
     market allowlist, progress fields on `/api/status`, and the owner-approved live gate
     values (paper cycles needed, capital cap, whether the acknowledgement exists) for display.
     Only approved values are shown; `TBD` or hypothesis values are not.
  5. No new dependency: drag, resize, and open are plain Pointer Events and the View
     Transitions API where available; `prefers-reduced-motion` turns the motion off. Static
     files are still served by exact name. A safety test checks that the page's scripts make
     only GET requests to `/api` and load nothing from another host.
- **Consequences:** The "road to live" bar counts cycles the session has run; the live gate
  counts completed paper cycles itself (`trader live preflight`), so the bar is a progress
  display, not the gate. The chart's price is now Kraken's (the venue the spot bot trades)
  instead of Jupiter's; `/api/prices` remains for the perps tools. Controls (start, stop, kill
  switch, linking an exchange) are still not on this page; they need authentication and
  their own ADR.
