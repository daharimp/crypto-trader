# ADR-039: AI review assistant with role-based reviewers (reports only, owner decides)

- **Status:** Accepted (2026-11-16; owner request)
- **Owner request (2026-11-16):** "the AI assistant that reviews bad days and suggests setting
  changes for you to approve? Yes and have it filled with sub agent assistants that can
  objectively analyze and do the work role based." Earlier: "if performance is bad that day a
  noti should be sent to stop and analyze"; "the ai assistant portion should help".
- **Context:** The paper perps accounts journal a bad day (`DAY_HALTED`, ADR-038) and stop new
  positions for the rest of the UTC day. The owner wants that day analyzed and improvements
  suggested, without giving an AI control of trading or risk values (CLAUDE.md: deterministic
  risk code has final authority; never invent risk values).
- **Decision:**
  1. `trader review run|show|watch` and a Compose service `review`. `watch` reviews each new
     bad day (today's or yesterday's) of the accounts in `configs/assistant.yaml` and sends a
     `[review]` phone alert; `run` reviews on demand; `--dry-run` prints the fact pack only.
  2. A deterministic fact pack (`trader.perps.review_facts`): the account's saved state, the
     day's events, recent closed trades, its settings file as written, and per-coin market
     facts from public 4h candles. All numbers come from code.
  3. Six roles, each a separate Claude request (`trader.perps.review_agents`) with a
     structured (JSON-schema) answer: market analyst, trade reviewer and risk officer run in
     parallel and see only the facts, so none anchors on another; a strategy researcher sees
     their notes and proposes at most three changes to an allowlist of strategy settings (or
     none); a skeptic gives a verdict on each; a lead editor writes the report.
  4. Code checks every proposal: a number, in range, and accepted by the same config checks
     the paper session runs (`resolve`) with only that value changed. Code renders the
     proposals table, so values cannot be misquoted. Profit-promising wording is flagged.
  5. It writes only `data/reports/` and its cursor `data/state/review-assistant.json`. It never
     edits a config, places an order, or touches the running sessions. The owner applies any
     change by hand, with a version increment and approval fields, as today.
  6. The key is read from `ANTHROPIC_API_KEY` in the server's `.env`; missing, every command
     exits 3. Model `claude-opus-5-5` with per-role effort, server-side refusal fallbacks on;
     both are settings in `configs/assistant.yaml`.
- **Consequences:** Reports cost API usage (six requests per review) and depend on
  api.anthropic.com being reachable from the server. AI analysis can be wrong; the skeptic and
  the code checks reduce but do not remove that. One bad day is a small sample, so most
  reports should end with "no change yet". The account list duplicates the one in the paper
  CLI (ADR-038) so this change does not depend on it; unify them once both are merged.
