# syntax=docker/dockerfile:1
# Builds the frontend once, then runs Caddy on one port: it serves the built pages and passes /api, the websocket
# and Reflex's own routes to the backend. Based on Reflex's docker-example/production.

# The address users open; the frontend is built with it so the browser finds the backend.
ARG API_URL=http://localhost:17300

FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /bin/uv
# Reflex uses a bun on PATH instead of downloading its own; this is the version Reflex 0.10.1 asks for.
COPY --from=oven/bun:1.4.4@sha256:1d22548f177f4ff38e0c15baa3c2c46c6c2060ba2d1bc573bb4720b407548f1d /usr/local/bin/bun /usr/local/bin/bun
ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Packages first, so a change to the app does not reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --extra postgres --no-install-project

COPY . .
RUN uv sync --locked --no-dev --extra postgres

ARG API_URL
RUN --mount=type=cache,target=/root/.bun/install/cache \
    REFLEX_API_URL=${API_URL} reflex export --frontend-only --no-zip


FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58

COPY --from=caddy:2.11.7@sha256:36c24ad91a7ff7bc4c87fe22bfa8df3c4b18da0773d73fc12ee2c52b98c0bb7e /usr/bin/caddy /usr/bin/caddy

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=17300 BACKEND_PORT=8000
# rxconfig.py sets a frontend port for local dev, which `--backend-only` refuses; 0 means none.
ENV REFLEX_FRONTEND_PORT=0

WORKDIR /app
# The app runs from .venv and never calls pip, so drop it and the packages it bundles.
# Reflex writes .states under /app and Caddy keeps its state under $HOME, so the app user owns /app.
RUN python -m pip uninstall --yes --no-input pip \
    && adduser --disabled-password --gecos "" --home /app studio && chown studio /app
COPY --chown=studio --from=builder /app/.venv .venv
COPY --chown=studio --from=builder /app/.web/backend .web/backend
COPY --from=builder /app/.web/build/client /srv
COPY --chown=studio . .
USER studio

EXPOSE 17300
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/v1/health', timeout=4)"]

CMD ["sh", "-c", "caddy start --config /app/Caddyfile --adapter caddyfile && exec reflex run --env prod --backend-only --backend-port \"$BACKEND_PORT\""]
