FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY paper_search_mcp ./paper_search_mcp

RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uv", "run", "--no-sync", "paper-search-mcp"]