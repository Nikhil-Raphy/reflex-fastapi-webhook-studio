# ADR-0001: One process — FastAPI in front of Reflex

## Status

Accepted

## Context

We could run the FastAPI app and the Reflex app as two services, but that means two deploys and two ports.

Reflex 0.10 can mount a FastAPI or Starlette app through `rx.App(api_transformer=...)`. We tried that on Reflex
0.10.0, FastAPI 0.143.0 and Python 3.14.6, and found two problems:

- Reflex mounts the FastAPI app as a sub-app, so a FastAPI `lifespan` never runs.
- Reflex puts its own CORS layer outside every app it mounts. That layer allows any origin with credentials and
  answers every preflight request itself. Our capture routes must store preflights and set their own CORS headers,
  and the management API must send none.

Granian, the server Reflex uses, calls the Reflex app as a factory to get the ASGI app it runs.

## Decision

Run one process, with our API in front of Reflex.

- `create_api()` in `reflex_fastapi_webhook_studio/api/app.py` builds the FastAPI app. Every route of ours lives
  under `/api`.
- `StudioApp`, a small `rx.App` subclass, overrides `__call__` and returns `ApiFirst(api, super().__call__())`.
- `ApiFirst` sends each HTTP request for `/api` or a path under it straight to the FastAPI app. Everything else,
  including lifespan and websocket traffic, goes to Reflex.
- Start-up and shut-down work, such as opening and closing the database, uses `app.register_lifespan_task`.

## Consequences

- In production mode (`reflex run --env prod --backend-port 17300`) one port serves the page and the API.
- In dev mode (`reflex run`) Reflex serves the page on port 17300 and the backend, with `/api`, on port 17301. Port
  17300 answers `/api` paths with the page HTML, because the dev frontend does not pass them to the backend.
- `rxconfig.py` sets both ports, and production mode refuses two different ports, so the production command passes
  `--backend-port 17300`.
- Requests under `/api` never meet Reflex's CORS layer. Capture routes set their own CORS headers, and see and store
  preflights. The management API under `/api/v1` sends no CORS headers.
- An unknown path under `/api` gets FastAPI's JSON 404.
- Reflex's own routes, such as `/_event` and `/ping`, keep Reflex's CORS layer.
- Our routes must stay clear of the routes Reflex keeps: `/_event`, `/ping`, `/_upload`, `/_health` and
  `/_all_routes`.
- Requests under `/api` skip Reflex's request context, so API code must not touch Reflex state.
- Lifespan tasks must import the names in their type hints at run time, because Reflex reads each task's
  signature when the server starts.
