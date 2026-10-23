# Reflex FastAPI Webhook Studio

Reflex FastAPI Webhook Studio catches webhooks and other HTTP requests so you can read them back. It is a web app
written in Python: a [Reflex](https://reflex.dev) app with a [FastAPI](https://fastapi.tiangolo.com) app in front of
it, in one process.

## What it does

You create a bin and get a URL. Any request sent to that URL, or to a path under it, is stored: the method, path,
query, headers in the order they came, and the exact body bytes. You read the stored requests back through a REST
API. This version has no pages of its own yet; the home page is the Reflex blank page.

## Run it

You need [uv](https://docs.astral.sh/uv/). uv fetches Python 3.14 for you.

```bash
uv sync
uv run alembic upgrade head
uv run reflex run
```

`alembic upgrade head` creates the database, `data/webhook_studio.db`. Run it again after each upgrade of the app.

In this dev mode, Reflex serves the page on one port and the API on another:

| What          | URL                                      |
| ------------- | ---------------------------------------- |
| Home page     | <http://localhost:17300>                 |
| API           | <http://localhost:17301/api/>            |
| API docs      | <http://localhost:17301/api/docs>        |

To serve both on one port, run the production build. Production mode needs the backend on the same port as the page:

```bash
uv run reflex run --env prod --backend-port 17300
```

Then the home page is at <http://localhost:17300> and the API under <http://localhost:17300/api/>.

## Use it

The examples use dev mode. In production mode, use port 17300.

```bash
BASE=http://localhost:17301

# Create a bin; the reply holds its id.
curl -s -X POST $BASE/api/v1/bins -H 'content-type: application/json' -d '{"label": "GitHub"}'
BIN=<the id from the reply>

# Send JSON, form data and a query string to it.
curl -s -X POST $BASE/api/webhook/$BIN -H 'content-type: application/json' -d '{"event": "push"}'
curl -s -X POST $BASE/api/webhook/$BIN/forms -d 'name=Ada&lang=python'
curl -s "$BASE/api/webhook/$BIN/search?tag=a&tag=b"

# List what it caught, newest first, then read one request in full.
curl -s "$BASE/api/v1/bins/$BIN/requests?limit=10"
curl -s $BASE/api/v1/bins/$BIN/requests/<request id>
```

The bin takes `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE` and `OPTIONS`, and stores whatever follows the bin id
as the path.

| The bin replies with                          | When                                                                    |
| --------------------------------------------- | ----------------------------------------------------------------------- |
| `200` and `{"ok": true, "request_id": "…"}`   | It stored the request. A `HEAD` reply has no body.                      |
| `204`                                         | CORS is on and a browser sent a preflight. The preflight is stored too. |
| `404`                                         | No bin has this id. Nothing is stored.                                  |
| `405`                                         | The method is not one of the seven above. Nothing is stored.            |
| `413` and the `request_id`                    | The body is over the size cap. The request is stored without its body.  |

A stored request holds its headers and query as lists of name and value pairs, in the order they came. The body is
in `body_base64`, and also in `body_text` when it is valid UTF-8.

## REST API

| Method | Path                                          | Purpose                                         |
| ------ | --------------------------------------------- | ----------------------------------------------- |
| any    | `/api/webhook/{bin_id}` and any path under it | Catch a request                                 |
| POST   | `/api/v1/bins`                                | Create a bin, with an optional label. Returns `201`. |
| GET    | `/api/v1/bins/{bin_id}`                       | Read a bin                                      |
| PATCH  | `/api/v1/bins/{bin_id}`                       | Change or clear the label                       |
| GET    | `/api/v1/bins/{bin_id}/requests`              | List requests, newest first; `limit` 1 to 100, 50 if left out |
| GET    | `/api/v1/bins/{bin_id}/requests/{request_id}` | Read one request in full                        |
| GET    | `/api/v1/health`                              | Check that the app and its database answer      |

Errors come as [problem details](https://www.rfc-editor.org/rfc/rfc9457) with the type
`application/problem+json`. The OpenAPI page is at `/api/docs` and the schema at `/api/openapi.json`.

## Configuration

The app reads these environment variables when it starts. It stops with an error that names the variable if a
value is wrong.

| Variable                              | Default                                      | Meaning                                                    |
| ------------------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `WEBHOOK_STUDIO_DATABASE_URL`         | `sqlite+aiosqlite:///data/webhook_studio.db` | Database URL. Use `sqlite+aiosqlite` or `postgresql+psycopg`. |
| `WEBHOOK_STUDIO_CORS_ENABLED`         | `true`                                       | CORS headers on capture replies, and answers to preflights. |
| `WEBHOOK_STUDIO_MAX_BODY_BYTES`       | `1048576`                                    | Largest body to store, in bytes.                           |
| `WEBHOOK_STUDIO_MAX_REQUESTS_PER_BIN` | `500`                                        | Most requests a bin keeps. The oldest go first.            |
| `WEBHOOK_STUDIO_MAX_BINS`             | `1000`                                       | Most bins the app holds. One more gets `409`.              |
| `WEBHOOK_STUDIO_LOG_LEVEL`            | `INFO`                                       | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`.          |

To keep your settings in a file, copy `.env.example` to `.env`, edit it, and load it with `set -a; . ./.env; set +a`
before you run `alembic` or `reflex`.

To use PostgreSQL, run `uv sync --extra postgres`, set `WEBHOOK_STUDIO_DATABASE_URL` to a
`postgresql+psycopg://` URL for an empty database, and run `uv run alembic upgrade head`.

## Security

- There are no accounts. The bin id is the secret: 22 characters holding 128 random bits. Anyone who has it can send
  to the bin and read all it caught.
- Every reply from `/api/webhook/` carries `Content-Security-Policy: sandbox` and `X-Content-Type-Options: nosniff`.
- With CORS on, capture replies carry `Access-Control-Allow-Origin: *`, never with credentials. The management API
  under `/api/v1` sends no CORS headers.
- If you put the app on the internet, expose only `/api/webhook/*`.
- Logs never hold bodies or header values, and show only the first 6 characters of a bin id.

## Decisions

The [decision records](adr/index.md) explain why the app is built this way.
