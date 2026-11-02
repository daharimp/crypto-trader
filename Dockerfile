# ai-crypto-trader: forward paper/live sessions (ADR-023). Build: docker compose build
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    TRADER_DATA_DIR=/app/data \
    TRADER_CONFIGS_DIR=/app/configs

RUN pip install --no-cache-dir "uv>=0.5,<1" && useradd --create-home --uid 1000 trader
WORKDIR /app

# Dependencies first (cached layer), then the code.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY schemas ./schemas
COPY experiments ./experiments
COPY scripts ./scripts

# configs/ and data/ are mounted from the host (see docker-compose.yml), so the owner edits
# configuration on the server and state survives image rebuilds. API keys come from .env.
RUN mkdir -p /app/data /app/configs && chown -R trader:trader /app
USER trader

ENTRYPOINT ["/app/.venv/bin/trader"]
CMD ["version"]
