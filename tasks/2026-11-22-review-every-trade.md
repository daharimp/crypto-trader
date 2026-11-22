# 2026-11-22: Make the review assistant analyze every trade (owner request)

- [x] Daily summary of every account after 00:10 UTC, reviewing every closed trade in the
      same request (owner: batch at end of day to save usage)
- [x] Drawdown alerts at 5/10/15 % from peak (code only)
- [x] Bad-day reviews include spot-perps
- [ ] Deploy to the server (git pull, docker compose build, docker compose up -d review)
