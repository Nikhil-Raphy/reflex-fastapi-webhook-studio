# Reflex FastAPI Webhook Studio

Reflex FastAPI Webhook Studio catches webhooks and other HTTP requests so you can read them back. It is a web app
written in Python: a [Reflex](https://reflex.dev) app with a [FastAPI](https://fastapi.tiangolo.com) app in front of
it, in one process.

## What it does

You make a bin and get a URL. Any request sent to that URL, or to a path under it, is stored: the method, path,
query, headers in the order they reached the app, and the exact body bytes. The bin's page in your browser shows
each request the moment it arrives, with no refresh.

From that page you can filter and search the requests, delete them, export the bin as JSON, copy a request as a curl
command, choose what the bin sends back, and send a request again to another URL. A REST API does the same for
scripts. A bin is deleted a week after its last request.

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

For a team, Docker Compose runs the app with PostgreSQL and Redis; see [Deploy with Docker](guide/deploy.md).

## Guides

- [Use the pages](guide/using.md): bins, filters, deletes, export, copy as curl, replies and replay.
- [REST API](guide/api.md): every route, with examples, the reply rules and the export format.
- [Configuration](guide/configuration.md): environment variables, PostgreSQL and several workers.
- [Deploy with Docker](guide/deploy.md): Compose, a proxy with TLS, and what to expose.

## Security

- There are no accounts. The bin id is the secret: 22 characters holding 128 random bits. Anyone who has it can send
  to the bin and read all it caught.
- With `WEBHOOK_STUDIO_BIN_LISTING=all`, anyone who can open the home page sees every bin id.
- Masked headers are hidden on screen only. The browser still receives their values.
- Every reply from `/api/webhook/` carries `Content-Security-Policy: sandbox` and `X-Content-Type-Options: nosniff`,
  the bin's own reply included. A reply may not set headers that would undo them.
- With CORS on, capture replies carry `Access-Control-Allow-Origin: *`, never with credentials. The management API
  under `/api/v1` sends no CORS headers.
- Replays reach only public internet addresses unless `WEBHOOK_STUDIO_REPLAY_MODE` is `local`.
- If you put the app on the internet, expose only `/api/webhook/*`.
- Logs never hold bodies or header values, and show only the first 6 characters of a bin id.

## Decisions

The [decision records](adr/index.md) explain why the app is built this way.
