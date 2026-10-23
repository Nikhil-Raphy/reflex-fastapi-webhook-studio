# Reflex FastAPI Webhook Studio

Catch, inspect and replay webhooks and HTTP requests.

## What it does

You create a bin and get a URL. Any request sent to that URL, or to a path under it, is stored: the method, path,
query, headers in the order they came, and the exact body bytes. You read the stored requests back through a REST
API.

The app is a [Reflex](https://reflex.dev) web app with a [FastAPI](https://fastapi.tiangolo.com) app in front of it,
in one Python process. It stores data in SQLite, or in PostgreSQL if you choose. This version has no pages of its
own yet: the home page is the Reflex blank page, and you work through the API with a tool such as curl.

## Quick start

You need [uv](https://docs.astral.sh/uv/). uv fetches Python 3.14 for you.

```bash
git clone https://github.com/Nikhil-Raphy/reflex-fastapi-webhook-studio.git
cd reflex-fastapi-webhook-studio
uv sync
uv run alembic upgrade head
uv run reflex run
```

`alembic upgrade head` creates the database, `data/webhook_studio.db`. Run it again after each upgrade of the app.

In this dev mode the home page is at <http://localhost:17300>, and the API runs on a second port:
<http://localhost:17301/api/v1/health>.

To serve both on one port, run the production build. Production mode needs the backend on the same port as the page:

```bash
uv run reflex run --env prod --backend-port 17300
```

Then the home page is at <http://localhost:17300> and the API under <http://localhost:17300/api/>.

## Using it

The examples below use dev mode. In production mode, use port 17300.

```bash
BASE=http://localhost:17301
```

### Create a bin

```bash
curl -s -X POST $BASE/api/v1/bins -H 'content-type: application/json' -d '{"label": "GitHub"}'
```

```text
{"id": "h-xohSG6xKnGPzKOrb_JVg", "label": "GitHub", "created_at": "2026-10-14T00:32:33.186454Z", ...}
```

The label is optional; send `{}` to leave it out. Keep the id, because it is the only key to the bin:

```bash
BIN=h-xohSG6xKnGPzKOrb_JVg
```

The bin's URL is `$BASE/api/webhook/$BIN`. Give it to the service that sends the webhooks.

### Send requests

Send JSON:

```bash
curl -s -X POST $BASE/api/webhook/$BIN -H 'content-type: application/json' -d '{"event": "push"}'
```

```json
{"ok": true, "request_id": "01a137d3-3e85-702c-be8d-84cdcc0283f7"}
```

Send form data to a path under the bin:

```bash
curl -s -X POST $BASE/api/webhook/$BIN/forms -d 'name=Ada&lang=python'
```

Send a query string, with a name that repeats:

```bash
curl -s "$BASE/api/webhook/$BIN/search?tag=a&tag=b"
```

The bin takes `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE` and `OPTIONS`. It stores whatever follows the bin id
as the path, here `/forms` and `/search`, and keeps each query value in order.

| The bin replies with                          | When                                                                    |
| --------------------------------------------- | ----------------------------------------------------------------------- |
| `200` and `{"ok": true, "request_id": "…"}`   | It stored the request. A `HEAD` reply has no body.                      |
| `204`                                         | CORS is on and a browser sent a preflight. The preflight is stored too. |
| `404`                                         | No bin has this id. Nothing is stored.                                  |
| `405`                                         | The method is not one of the seven above. Nothing is stored.            |
| `413` and the `request_id`                    | The body is over the size cap. The request is stored without its body.  |

### Read what a bin caught

List the newest requests first. `limit` runs from 1 to 100 and is 50 if you leave it out:

```bash
curl -s "$BASE/api/v1/bins/$BIN/requests?limit=10"
```

Read one request in full:

```bash
curl -s $BASE/api/v1/bins/$BIN/requests/01a137d3-3e85-702c-be8d-84cdcc0283f7
```

The reply holds the headers and query as lists of name and value pairs, in the order they came. The body is in
`body_base64`, and also in `body_text` when it is valid UTF-8.

### Rename a bin

```bash
curl -s -X PATCH $BASE/api/v1/bins/$BIN -H 'content-type: application/json' -d '{"label": "Stripe"}'
```

Send `{"label": null}` to clear the label.

## Configuration

The app reads these environment variables when it starts. It stops with an error that names the variable if a
value is wrong.

| Variable                              | Default                                      | Meaning                                                    |
| ------------------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `WEBHOOK_STUDIO_DATABASE_URL`         | `sqlite+aiosqlite:///data/webhook_studio.db` | Database URL. Use `sqlite+aiosqlite` or `postgresql+psycopg`. |
| `WEBHOOK_STUDIO_CORS_ENABLED`         | `true`                                       | CORS headers on capture replies, and answers to preflights. |
| `WEBHOOK_STUDIO_MAX_BODY_BYTES`       | `1048576`                                    | Largest body to store, in bytes.                           |
| `WEBHOOK_STUDIO_MAX_REQUESTS_PER_BIN` | `500`                                        | Most requests a bin keeps. The oldest go first.            |
| `WEBHOOK_STUDIO_MAX_BINS`             | `1000`                                       | Most bins the app holds.                                   |
| `WEBHOOK_STUDIO_LOG_LEVEL`            | `INFO`                                       | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`.          |

To keep your settings in a file, copy `.env.example` to `.env`, edit it, and load it into your shell before you run
`alembic` or `reflex`:

```bash
cp .env.example .env
set -a; . ./.env; set +a
```

To use PostgreSQL, install its driver, point the URL at an empty database, and create the tables:

```bash
uv sync --extra postgres
export WEBHOOK_STUDIO_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/webhook_studio
uv run alembic upgrade head
```

## REST API

| Method | Path                                          | Purpose                                         |
| ------ | --------------------------------------------- | ----------------------------------------------- |
| any    | `/api/webhook/{bin_id}` and any path under it | Catch a request                                 |
| POST   | `/api/v1/bins`                                | Create a bin, with an optional label. Returns `201`. |
| GET    | `/api/v1/bins/{bin_id}`                       | Read a bin                                      |
| PATCH  | `/api/v1/bins/{bin_id}`                       | Change or clear the label                       |
| GET    | `/api/v1/bins/{bin_id}/requests`              | List requests, newest first                     |
| GET    | `/api/v1/bins/{bin_id}/requests/{request_id}` | Read one request in full                        |
| GET    | `/api/v1/health`                              | Check that the app and its database answer      |

`GET /api/v1/health` returns `{"status": "ok", "version": "<app version>", "database": "ok"}`, or `503` if the
database does not answer.

Errors come as [problem details](https://www.rfc-editor.org/rfc/rfc9457) with the type
`application/problem+json`. The app serves its OpenAPI page at `/api/docs` and the schema at `/api/openapi.json`.

## Limits

- A body over `WEBHOOK_STUDIO_MAX_BODY_BYTES` (1 MiB by default) is not stored. The app stops reading it at the cap,
  replies `413`, and stores the request with `body_truncated` set and no body.
- A bin keeps its newest `WEBHOOK_STUDIO_MAX_REQUESTS_PER_BIN` requests (500 by default).
- The app holds at most `WEBHOOK_STUDIO_MAX_BINS` bins (1000 by default). Creating one more gets `409`.
- A label is 1 to 80 characters.
- PostgreSQL cannot store the NUL character in text, so the app shows it as U+FFFD in the stored path, query, headers
  and content type. The stored body is always exact.

## Security notes

- There are no accounts. The bin id is the secret: 22 characters holding 128 random bits. Anyone who has it can send
  to the bin and read all it caught, so share it only with the services that send to it.
- Every reply from `/api/webhook/` carries `Content-Security-Policy: sandbox` and `X-Content-Type-Options: nosniff`,
  so a browser that opens a bin's URL runs nothing from it with the app's origin.
- With CORS on, capture replies carry `Access-Control-Allow-Origin: *`, never with credentials, so a web page can send
  test requests to a bin. The management API under `/api/v1` sends no CORS headers. Set
  `WEBHOOK_STUDIO_CORS_ENABLED=false` to turn CORS off.
- If you put the app on the internet, expose only `/api/webhook/*`. Keep the pages and `/api/v1` on a private
  network.
- Logs never hold bodies or header values, and show only the first 6 characters of a bin id.

## How it works

### Use cases

![Use cases](docs/diagrams/01-use-case.png)

A sender, such as a webhook service or curl, sends requests to a bin. A developer creates bins and reads what they
caught. An operator runs the server and sets it up.

### Context

![Context](docs/diagrams/02-c4-context.png)

Senders and developers both talk to the app over HTTP.

### Containers

![Containers](docs/diagrams/03-c4-container.png)

Reflex turns the Python UI into a React app that runs in the browser. One worker process runs the API and the Reflex
backend, and keeps data in SQLite or PostgreSQL.

### Components

![Components](docs/diagrams/04-c4-component.png)

`ApiFirst` sends each request under `/api` to the FastAPI app, and everything else to Reflex. Routers call services,
services call the repository, and the repository talks to the database.

### Packages

![Packages](docs/diagrams/05-packages.png)

Each layer imports only the layers below it.

### Classes

![Classes](docs/diagrams/06-classes.png)

The domain types are frozen dataclasses. The services and the repository take and return them.

### Data model

![Data model](docs/diagrams/07-data-model.png)

A bin has many captured requests. Deleting a bin deletes its requests.

### Capturing a request

![Capturing a request](docs/diagrams/09-seq-capture.png)

The capture route stores the request, drops the oldest past the cap and updates the bin, all in one transaction.

### Capture checks

![Capture checks](docs/diagrams/13-activity-capture.png)

The checks the capture route makes, in order, and the reply each one leads to.

### Deployment

![Deployment](docs/diagrams/15-deployment.png)

Dev mode runs a frontend dev server on port 17300 and the backend on port 17301. Production mode serves everything
from one process on port 17300.

### CI, docs and releases

![CI, docs and releases](docs/diagrams/16-activity-ci.png)

Each pull request runs lint, tests on SQLite and PostgreSQL, and a scan of the locked packages for known flaws. Each
push to `main` also builds the docs site and updates the release pull request.

## Links

- [Docs site](https://nikhil-raphy.github.io/reflex-fastapi-webhook-studio/)
- [Decision records](docs/adr/index.md)

## Contributions

This is a personal project. It takes no code contributions for now, but you may open an issue to report a bug or ask
for a feature.

## License

[Apache-2.0](LICENSE). Copyright 2026 Nikhil-Raphy.
