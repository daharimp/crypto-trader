# 2026-11-26: Add-ons for the bots, tested first (owner request: "yes add these bot improvements")

Owner approved testing a pause after stop-outs with a cooldown after each loss, correlation
sizing and a time limit, then sizing by confidence inside a range ("it should be assessed
based on confidence"). Values still need the owner's yes; nothing is reset; nothing is live.

- [x] EXP-2026-025: cooldown, stop guard, correlation sizing, time limit on four slices;
      only the cooldown after a losing trade passes (4, 12 and 24 hours)
- [x] EXP-2026-026: five confidence measures on seven slices; the composite earns the range
      under the plan's rule, narrowly (results file lists the four caveats)
- [x] Cooldown as an optional per-account setting, off unless set (ADR-053);
      `tests/unit/test_perps_cooldown.py`; the built setting matches the research cooldown
      event for event (`run_exp025.py engine-S1..S4`)
- [x] Unknown keys under `risk:` are refused
- [ ] Owner decision UD-34: cooldown length for the ten-coin account (4, 12, 24 hours or none)
- [ ] Size range per account as a setting (smallest and largest size per trade); the
      composite chooses inside it only where the owner switches it on
- [ ] Owner decision: where confidence sizing runs first, and with which range
