# 2026-11-15: Trader Desk as sections you slide between (owner request)

Owner: "the ui design needs to be better, show the positions/trades"; prefers sliding to
click-through pages; asked for the crypto-trader design system, a lighter look, and a choice
of appearance. Design canvas reviewed by the owner first. Builds on
`tasks/2026-11-15-perps-paper-history.md`.

- [x] ADR-037 (supersedes the layout part of ADR-030)
- [x] Four sliding sections with swipe, arrow keys and tabs; account switch (leverage, spot)
- [x] Positions with leverage, liquidation price and distance; a detail sheet that slides in
- [x] Trades with dollars won or lost; liquidations marked
- [x] Account-value chart from the recorded history
- [x] Appearance: Auto, Light, Dark, Day and night (saved in the browser only)
- [x] Design-system colours and bundled fonts; `--edge` border for pressable things
- [x] Tests: new static files and fonts by exact name; scripts and stylesheet load nothing
      remote and make only GET requests to `/api`
- [x] Checked in Chromium at phone (iPhone 14) and desktop (1440 wide) sizes, light and dark
- [ ] Later: review questions; private control panel (own ADR); finer account-value history
- [ ] Owner: merge, then `docker compose up -d --build dashboard` (RUNBOOK 8a)
