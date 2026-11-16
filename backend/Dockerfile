# Backend image (Phase 11). Build from the repository root so data/ and scripts/ are included:
#   docker build -f backend/Dockerfile -t agentops-api .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app/backend

# Dependencies first (cached until uv.lock changes), exactly as locked, without dev tools.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# App code, then the repository data (scenarios, SOPs, agents, suites) and scripts.
COPY backend/ ./
COPY data/ /app/data/
COPY scripts/ /app/scripts/
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

ENV PATH="/app/backend/.venv/bin:$PATH" \
    APP_ENV=production \
    PORT=8000
EXPOSE 8000

CMD ["sh", "start.sh"]
