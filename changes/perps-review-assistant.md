### Added
- AI review assistant (ADR-039): `trader review run|show|watch` and Compose service `review`.
  On a paper account's bad day, six role-based reviewers (market analyst, trade reviewer, risk
  officer, strategy researcher, skeptic, lead editor) write a plain-language report from a
  measured fact pack and propose at most three setting changes, each checked by code; it never
  changes settings or places orders. Settings in `configs/assistant.yaml`; key from
  `ANTHROPIC_API_KEY` in `.env`. New dependency: `anthropic`.
