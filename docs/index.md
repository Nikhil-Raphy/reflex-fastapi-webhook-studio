# Reflex FastAPI Webhook Studio

Reflex FastAPI Webhook Studio is a web app written in Python. It runs a [Reflex](https://reflex.dev) app with a
[FastAPI](https://fastapi.tiangolo.com) app mounted inside it, in one process.

## What it does

This version is the base of the app. It serves:

- a home page, the Reflex blank page;
- `GET /api/v1/health`, which returns `{"status": "ok", "version": "<app version>"}`.

## Run it

You need [uv](https://docs.astral.sh/uv/). uv fetches Python 3.14 for you.

```bash
uv sync
uv run reflex run
```

In this dev mode, Reflex serves the page on one port and the API on another:

| What          | URL                                      |
| ------------- | ---------------------------------------- |
| Home page     | <http://localhost:17300>                 |
| Health check  | <http://localhost:17301/api/v1/health>   |

To serve both on one port, run the production build. Production mode needs the backend on the same port as the page:

```bash
uv run reflex run --env prod --backend-port 17300
```

Then the home page is at <http://localhost:17300> and the health check at <http://localhost:17300/api/v1/health>.

## Decisions

The [decision records](adr/index.md) explain why the app is built this way.
