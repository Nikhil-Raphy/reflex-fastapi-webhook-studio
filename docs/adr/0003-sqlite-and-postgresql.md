# ADR-0003: SQLite by default, PostgreSQL as an option

## Status

Accepted

## Context

One person must be able to run the app with nothing more to install. A shared server, where several requests write
at once, is better served by PostgreSQL. The code should not care which one it talks to.

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

## Consequences

- A fresh clone runs with SQLite and no other service.
- The tests run on SQLite every time, and on PostgreSQL too when `WEBHOOK_STUDIO_TEST_DATABASE_URL` points to an
  empty PostgreSQL database. CI runs a PostgreSQL 18 service container for this.
- The text form of a request can differ from what the sender sent where it held a NUL. The stored body is exact.
- The app does not move data from SQLite to PostgreSQL.
