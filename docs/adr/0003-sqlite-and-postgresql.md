# ADR-0003: SQLite by default, PostgreSQL as an option

## Status

Accepted

## Context

One person must be able to run the app with nothing more to install. A shared server, where several requests write
at once, is better served by PostgreSQL. The code should not care which one it talks to. A small team wants one
command that starts the app, its database and Redis together.

## Decision

- By default, use SQLite through `aiosqlite`, in the file `data/webhook_studio.db`. The app makes the folder if it
  is missing. Each new connection sets `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON` and
  `synchronous=NORMAL`.
- Use PostgreSQL through `psycopg` when `WEBHOOK_STUDIO_DATABASE_URL` starts with `postgresql+psycopg://`. Install
  the driver with `uv sync --extra postgres`.
- Refuse any other driver at start-up.
- Keep the schema and queries the same on both:
  - JSON columns use `JSON`, with a `JSONB` variant on PostgreSQL.
  - Time columns store UTC. SQLite keeps no time zone, so `UtcDateTime` stores a plain UTC value there and adds the
    zone back on read.
  - Trimming a bin to its newest requests is one `DELETE` with a subquery that both engines run.
  - Alembic uses batch mode on SQLite, which cannot alter most columns in place.
- PostgreSQL text and JSON columns refuse the NUL character. Before storing the path, query, headers and content
  type, the app replaces each NUL with U+FFFD. The body column stores the bytes as they came.
- For a team, `compose.yaml` runs four services: `app`, a one-shot `migrate` that runs `alembic upgrade head`,
  `postgres` and `redis`. `app` starts only after `migrate` ends well. Each image is pinned by digest.
- The `Dockerfile` follows Reflex's own production example. A build stage installs the locked packages with uv and
  builds the pages with bun. The final stage holds Python, the app and Caddy, but not pip, bun or `node_modules`, and
  runs as a user without root rights. Caddy serves the built pages on port 17300 and passes the backend routes to
  `reflex run --env prod --backend-only`. `rxconfig.py` sets a dev frontend port, which `--backend-only` refuses, so
  the image sets `REFLEX_FRONTEND_PORT=0`.

## Consequences

- A fresh clone runs with SQLite and no other service.
- The tests run on SQLite every time, and on PostgreSQL too when `WEBHOOK_STUDIO_TEST_DATABASE_URL` points to an
  empty PostgreSQL database. CI runs a PostgreSQL 18 service container for this.
- The text form of a request can differ from what the sender sent where it held a NUL. The stored body is exact.
- The app does not move data from SQLite to PostgreSQL.
- The pages are built with `APP_URL`, so changing it means rebuilding the image. In the browser, Reflex swaps a
  `localhost` address for the host the page came from, and drops the port under HTTPS, so a proxy with TLS works.
- Behind the image's Caddy every request comes from `127.0.0.1`, so the app takes the sender's address from the last
  `X-Forwarded-For` entry, but only from a peer on the same machine.
- CI builds the image, starts the whole stack and sends a request through it on every pull request.
