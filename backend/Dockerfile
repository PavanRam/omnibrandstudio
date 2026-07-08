# ── Stage 1: dependency installer ────────────────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN groupadd -r omnibrand && useradd -r -g omnibrand -u 10001 omnibrand

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN chown -R omnibrand:omnibrand /app
USER omnibrand

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
