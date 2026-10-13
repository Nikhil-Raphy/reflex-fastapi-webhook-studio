# ADR-0001: One process — FastAPI mounted in Reflex

## Status

Accepted

## Context

We could run the FastAPI app and the Reflex app as two services, but that means two deploys and two ports.

Reflex 0.10 takes a FastAPI or Starlette app through `rx.App(api_transformer=...)` and serves it from the Reflex
backend. We checked the points below on Reflex 0.10.0, FastAPI 0.143.0 and Python 3.14.6.

## Decision

Run one process. `create_api()` in `reflex_fastapi_webhook_studio/api/app.py` builds the FastAPI app, and the Reflex
app mounts it with `api_transformer`. Every route of ours lives under `/api`. Today that is `GET /api/v1/health`.

## Consequences

- In production mode (`reflex run --env prod --backend-port 17300`) one port serves the page and the API. An unknown
  path under `/api` gets the frontend's 404 page.
- In dev mode (`reflex run`) Reflex serves the page on port 17300 and the backend, with `/api`, on port 17301. Port
  17300 answers `/api` paths with the page HTML, because the dev frontend does not pass them to the backend.
- `rxconfig.py` sets both ports, and production mode refuses two different ports, so the production command passes
  `--backend-port 17300`.
- Our routes must stay clear of the routes Reflex keeps: `/_event`, `/ping`, `/_upload`, `/_health` and
  `/_all_routes`.
- Reflex mounts the FastAPI app as a sub-app, so a FastAPI `lifespan` never runs. Start-up and shut-down work must
  use `app.register_lifespan_task`, which starts and stops with the server.
- Reflex wraps the mounted app in its own CORS layer. That layer allows any origin and answers every preflight
  request.
