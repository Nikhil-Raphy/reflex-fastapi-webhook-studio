# Configuration

The app reads these environment variables when it starts. It stops with an error that names the variable if a
value is wrong.

| Variable                              | Default                                      | Meaning                                                    |
| ------------------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `WEBHOOK_STUDIO_DATABASE_URL`         | `sqlite+aiosqlite:///data/webhook_studio.db` | Database URL. Use `sqlite+aiosqlite` or `postgresql+psycopg`. |
| `WEBHOOK_STUDIO_CORS_ENABLED`         | `true`                                       | CORS headers on capture replies, and answers to preflights. |
| `WEBHOOK_STUDIO_MAX_BODY_BYTES`       | `1048576`                                    | Largest body to store, in bytes.                           |
| `WEBHOOK_STUDIO_MAX_REQUESTS_PER_BIN` | `500`                                        | Most requests a bin keeps. The oldest go first.            |
| `WEBHOOK_STUDIO_MAX_BINS`             | `1000`                                       | Most bins the app holds. One more gets `409`.              |
| `WEBHOOK_STUDIO_BIN_TTL_DAYS`         | `7`                                          | Days a bin lives after its last request.                   |
| `WEBHOOK_STUDIO_SWEEP_INTERVAL_S`     | `3600`                                       | Seconds between deletes of expired bins. Each worker deletes them, at a slightly random time. |
| `WEBHOOK_STUDIO_BIN_LISTING`          | `browser`                                    | Which bins the home page lists: `browser` or `all`.         |
| `WEBHOOK_STUDIO_MAX_DELAY_MS`         | `30000`                                      | Longest reply delay a bin may set, in milliseconds.        |
| `WEBHOOK_STUDIO_REPLAY_MODE`          | `restricted`                                 | `restricted`: replays reach public internet addresses only. `local`: any address, this machine included. |
| `WEBHOOK_STUDIO_REPLAY_TIMEOUT_S`     | `15`                                         | Seconds a replay may take in all.                          |
| `WEBHOOK_STUDIO_PUBLIC_BASE_URL`      | unset                                        | The scheme and host senders use, such as `https://hooks.example.com`. Capture URLs and curl commands use it. No path. |
| `WEBHOOK_STUDIO_LOG_LEVEL`            | `INFO`                                       | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`.          |
| `REFLEX_REDIS_URL`                    | unset                                        | A Redis URL. When set, Reflex keeps page state in Redis and can run several workers, and live updates travel through it. |

## A settings file

Copy `.env.example` to `.env`, edit it, and load it into your shell before you run `alembic` or `reflex`:

```bash
cp .env.example .env
set -a; . ./.env; set +a
```

Docker Compose reads the same file by itself. The values it needs for itself are in
[Deploy with Docker](deploy.md).

## PostgreSQL

Install the driver, point the URL at an empty database, and create the tables:

```bash
uv sync --extra postgres
export WEBHOOK_STUDIO_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/webhook_studio
uv run alembic upgrade head
```

Run `uv run alembic upgrade head` again after each upgrade of the app.

## Several workers

One worker needs no Redis. To run several, set `REFLEX_REDIS_URL`. Reflex then keeps each tab's page state in Redis,
and the app sends live updates through Redis, so a page shows every request whichever worker caught it.
