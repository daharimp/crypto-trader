# ADR-037: Dashboard as sections you slide between, in the project's design system

- **Status:** Accepted (2026-11-15; owner asked for a better design that shows positions and
  trades, said sliding between screens suits them better than tapping through to separate
  pages, and asked for the crypto-trader design system, a light look, and a choice of
  appearance). Supersedes the layout part of ADR-030.
- **Context:** The ADR-030 workspace (seven cards to drag, resize, hide and open) showed the
  leverage paper account in one card without liquidation prices, closed trades or a value
  history, and the owner found it plain. The owner's focus is the leverage paper account
  (UD-24), on a phone and a Mac.
- **Decision:**
  1. The page is four sections side by side: **Overview**, **Positions**, **Trades**,
     **Markets**. Swipe sideways (touch or trackpad), press the left and right arrow keys, or
     tap a section name to slide between them. It is the same on a phone and a computer; a
     wider screen gives each section more columns. The address ends in the section's name
     (`#positions`), so a reload stays put.
  2. One switch at the top picks the account: **Leverage · paper** (default) or **Spot**.
     Both use the same three account sections.
  3. Tapping a position slides a sheet in (from the bottom on a phone, from the right on a
     computer) with its size, the owner's money in it, entry, price now, liquidation price
     and distance. Escape, Close, or the backdrop closes it.
  4. **Appearance:** Auto (follows the device), Light, Dark, or Day and night (light 7am to
     7pm by the device's clock). Saved in the browser's `localStorage` only. A web page
     cannot read the room's light level, so "adapt to brightness" is the device's own
     automatic appearance, which Auto follows.
  5. Colours, type and radii come from the design system synced from
     `docs/profile-builder/template.html`. Its three fonts (Bricolage Grotesque, Instrument
     Sans, JetBrains Mono; SIL Open Font License 1.1) are **bundled** under
     `static/fonts/`, because the page may load nothing from another host. One addition: an
     `--edge` border colour (at least 3:1) for things you can press, since the system's
     `--line` is about 1.4:1. The profile builder is not changed.
  6. Dragging, resizing and hiding cards (ADR-030 items 1 to 3) are removed. Everything else
     in ADR-030 and ADR-026 stands: the server is **GET only**, static files are served by
     exact name, the scripts make only GET requests to `/api`, and nothing remote loads. The
     safety test now also checks the stylesheet.
- **Consequences:** The saved card layout from ADR-030 is ignored (its `localStorage` key is
  left alone). Liquidation distance is drawn amber inside 15%; that number is a display
  choice, not a risk limit, and changes nothing the bot does. The account-value chart has one
  point per day until the session records more. Review questions and anything that changes a
  setting are not on this page; the private control panel needs its own ADR.
