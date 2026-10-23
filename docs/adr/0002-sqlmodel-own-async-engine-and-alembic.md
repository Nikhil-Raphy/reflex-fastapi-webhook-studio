# ADR-0002: SQLModel with our own async engine and Alembic

## Status

Accepted

## Context

The app must store bins and the requests they catch. Reflex ships `rx.Model` and `reflex db`, but `rx.Model` has
been deprecated since Reflex 0.9.2, and the Reflex docs tell new apps to use SQLModel or SQLAlchemy with their own
engine and sessions.

FastAPI handlers run on the event loop, so a blocking database driver would stall every request.

## Decision

- Define each table as a `SQLModel` class with `table=True` in `reflex_fastapi_webhook_studio/db/models.py`:
  `BinRow` and `CapturedRequestRow`.
- Build one `AsyncEngine` and one `async_sessionmaker` in `db/engine.py`, inside the `Database` class, from
  `WEBHOOK_STUDIO_DATABASE_URL`. The app opens the database in a Reflex lifespan task and disposes of the engine on
  shut-down.
- Use `aiosqlite` for SQLite and `psycopg` in async mode for PostgreSQL. `psycopg` comes with the `postgres` extra.
- Run plain Alembic, with an async `alembic/env.py` and our own `alembic.ini`. Do not use `reflex db`.
- Functions in `db/repository.py` take a session and return the frozen dataclasses in `domain.py`, never table
  rows. The services own the transactions.

## Consequences

- The app does not depend on a Reflex API that is going away.
- Each new schema needs a migration in `alembic/versions/`, and each install runs `uv run alembic upgrade head`
  before the first start.
- The table, domain and API layers each list the same fields. The repository maps rows to domain types by hand.
- FastAPI builds reply schemas from the domain dataclasses, so the types their fields name must import at run time,
  not only under `TYPE_CHECKING`.
