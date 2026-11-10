# Getting help

| I want to... | Go to |
|---|---|
| Set up the server, go from paper to live, operate the bot | [`docs/operations/RUNBOOK.md`](docs/operations/RUNBOOK.md) |
| Stop trading **now** | `docker compose run --rm cli killswitch engage --reason "..."` (RUNBOOK §7) |
| Sell everything now | `docker compose run --rm cli session flatten --reason "..."` |
| See what the bot is doing | `docker compose run --rm cli session status` and `docker compose logs --tail 200 live` |
| Understand why a run is refused | `trader profile validate PROFILE --environment paper|live` lists every error and unresolved decision |
| Understand a risk rule or decision ID | `docs/spec/` (start with `README.md`), `docs/decisions/` |
| Report a security problem | [`SECURITY.md`](SECURITY.md) (privately, never in a public issue) |
| Report a bug or ask for a feature | Open an issue with the templates provided |

When asking for help, include the command you ran, its exit code, and the last lines of the
log. **Never include API keys, `.env` contents, or webhook URLs.**
