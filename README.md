# Reflex FastAPI Webhook Studio

Catch, inspect and replay webhooks and HTTP requests.

## What it does

You make a bin and get a URL. Any request sent to that URL, or to a path under it, is stored: the method, path,
query, headers in the order they came, and the exact body bytes. The bin's page in your browser shows each request
the moment it arrives, with no refresh. A REST API gives the same data to scripts.

The app is a [Reflex](https://reflex.dev) web app with a [FastAPI](https://fastapi.tiangolo.com) app in front of it,
in one Python process. It stores data in SQLite, or in PostgreSQL if you choose.

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

Open <http://localhost:17300>. In this dev mode the API runs on a second port, for example
<http://localhost:17301/api/v1/health>.

To serve both on one port, run the production build. Production mode needs the backend on the same port as the page:

```bash
uv run reflex run --env prod --backend-port 17300
```

Then the pages are at <http://localhost:17300> and the API under <http://localhost:17300/api/>.

## Using it

### Make a bin

On the home page, type a label if you want one and press **New bin**. The bin's page opens and shows its URL, with
a **Copy URL** button. Give that URL to the service that sends the webhooks.

The home page lists the bins made in this browser, with how many requests each holds. To open a bin made
elsewhere, paste its id, its URL or its page address into the **Open a bin** box.

### Send requests

The bin's URL ends in `/api/webhook/` and the bin id. While the bin is empty, its page shows a curl command to copy.
The examples below use dev mode; in production mode, use port 17300.

```bash
URL=http://localhost:17301/api/webhook/h-xohSG6xKnGPzKOrb_JVg
curl -s -X POST $URL -H 'content-type: application/json' -d '{"event": "push"}'
curl -s -X POST $URL/forms -d 'name=Ada&lang=python'
curl -s "$URL/search?tag=a&tag=b"
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

### Inspect requests

The bin's page lists its requests on the left, newest first. Each row shows the method in a colour of its own, the
path and how long ago it came. Click a row to see it on the right, in four tabs:

- **Overview:** the request id, time, method, path, query string, content type, body size, client address, HTTP
  version and the status sent back.
- **Headers:** every header in the order it came. Headers that often hold secrets, such as `Authorization`,
  `Cookie` and names holding `token`, `secret`, `signature`, `api-key`, `password` or `session`, show as `••••` until
  you click them.
- **Query:** the raw query string, and each name and value in order.
- **Body:** JSON laid out with indents, form data as a table, other text as it came, and binary bodies as their size
  with a **Download** button for the exact bytes. The page never renders a body as HTML.

### Live updates

New requests appear at once, in every tab that has the bin open. A dot at the top right shows the state: **Live**
(green) while the page follows the bin, **Connecting** (amber) while it connects or reconnects, and **Offline** (red)
when it cannot reach the server. After a reconnect the page reloads the bin, so it misses nothing.

### Use the REST API

The same data is open to scripts. Make a bin, then list and read what it caught:

```bash
BASE=http://localhost:17301
curl -s -X POST $BASE/api/v1/bins -H 'content-type: application/json' -d '{"label": "GitHub"}'
BIN=h-xohSG6xKnGPzKOrb_JVg   # the id from the reply
curl -s "$BASE/api/v1/bins/$BIN/requests?limit=10"
curl -s $BASE/api/v1/bins/$BIN/requests/01a137d3-3e85-702c-be8d-84cdcc0283f7
```

A request reply holds the headers and query as lists of name and value pairs, in the order they came. The body is
in `body_base64`, and also in `body_text` when it is valid UTF-8. To rename a bin, send
`PATCH $BASE/api/v1/bins/$BIN` with `{"label": "Stripe"}`, or `{"label": null}` to clear the label; an open page
shows the new label at once.

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
| `WEBHOOK_STUDIO_BIN_LISTING`          | `browser`                                    | Which bins the home page lists: `browser` for the ones made in this browser, `all` for every bin. |
| `WEBHOOK_STUDIO_LOG_LEVEL`            | `INFO`                                       | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`.          |
| `REFLEX_REDIS_URL`                    | unset                                        | A Redis URL. When set, Reflex keeps page state in Redis and can run several workers, and live updates travel through the same Redis. |

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
| GET    | `/api/v1/bins`                                | List every bin with its request count. Only when `WEBHOOK_STUDIO_BIN_LISTING` is `all`; otherwise `404`. |
| GET    | `/api/v1/bins/{bin_id}`                       | Read a bin                                      |
| PATCH  | `/api/v1/bins/{bin_id}`                       | Change or clear the label                       |
| GET    | `/api/v1/bins/{bin_id}/requests`              | List requests, newest first; `limit` 1 to 100, 50 if left out |
| GET    | `/api/v1/bins/{bin_id}/requests/{request_id}` | Read one request in full                        |
| GET    | `/api/v1/health`                              | Check that the app, its database and Redis, when used, answer |

`GET /api/v1/health` returns `{"status": "ok", "version": "<app version>", "database": "ok"}`, with `"redis": "ok"`
added when the app uses Redis. It returns `503`, naming the failed check, if the database or Redis does not answer.

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
- With `WEBHOOK_STUDIO_BIN_LISTING=all`, anyone who can open the home page sees every bin id. Keep the default,
  `browser`, unless everyone who can reach the pages may see every bin.
- Masked headers are hidden on screen only, so they do not show in a screenshot or over a shoulder. The browser
  still receives their values.
- Every reply from `/api/webhook/` carries `Content-Security-Policy: sandbox` and `X-Content-Type-Options: nosniff`,
  so a browser that opens a bin's URL runs nothing from it with the app's origin.
- With CORS on, capture replies carry `Access-Control-Allow-Origin: *`, never with credentials, so a web page can send
  test requests to a bin. The management API under `/api/v1` sends no CORS headers. Set
  `WEBHOOK_STUDIO_CORS_ENABLED=false` to turn CORS off.
- If you put the app on the internet, expose only `/api/webhook/*`. Keep the pages and `/api/v1` on a private
  network.
- Logs never hold bodies or header values, and show only the first 6 characters of a bin id.

## How it works

### Context

![Context](docs/diagrams/01-c4-context.png)

Senders and developers both talk to the app over HTTP.

### Containers

![Containers](docs/diagrams/02-c4-container.png)

Reflex turns the Python UI into a React app that runs in the browser. Each worker process runs the API and the Reflex
backend, and keeps data in SQLite or PostgreSQL. With Redis, several workers share page state and live updates.

### Data model

![Data model](docs/diagrams/03-data-model.png)

A bin has many captured requests. Deleting a bin deletes its requests.

### Capturing a request

![Capturing a request](docs/diagrams/04-seq-capture.png)

The capture route stores the request, drops the oldest past the cap and updates the bin, all in one transaction,
then publishes the event.

### Live push

![Live push](docs/diagrams/05-seq-live-push.png)

Each open bin page runs one watch task. It subscribes, reloads, then adds each new request and checks every 15 s
that its tab is still open. With Redis, every worker hears every event.

### Deployment

![Deployment](docs/diagrams/06-deployment.png)

Dev mode runs a frontend dev server on port 17300 and the backend on port 17301. Production mode serves everything
from one process on port 17300.

## Links

- [Docs site](https://nikhil-raphy.github.io/reflex-fastapi-webhook-studio/)
- [Decision records](docs/adr/index.md)

## Contributions

This is a personal project. It takes no code contributions for now, but you may open an issue to report a bug or ask
for a feature.

## License

[Apache-2.0](LICENSE). Copyright 2026 Nikhil-Raphy.
