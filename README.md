# Reflex FastAPI Webhook Studio

Catch, inspect and replay webhooks and HTTP requests.

## What it does

You make a bin and get a URL. Any request sent to that URL, or to a path under it, is stored: the method, path,
query, headers in the order they reached the app, and the exact body bytes. The bin's page in your browser shows
each request the moment it arrives, with no refresh.

From that page you can filter and search the requests, delete them, export the bin as JSON, copy a request as a curl
command, choose what the bin sends back, and send a request again to another URL. A REST API does the same for
scripts. A bin is deleted a week after its last request.

The app is a [Reflex](https://reflex.dev) web app with a [FastAPI](https://fastapi.tiangolo.com) app in front of it,
in one Python process. It stores data in SQLite, or in PostgreSQL if you choose. For a team, Docker Compose runs it
with PostgreSQL and Redis, so several workers share the load.

## Quick start, local

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

## Quick start, Docker

You need Docker with Compose.

```bash
git clone https://github.com/Nikhil-Raphy/reflex-fastapi-webhook-studio.git
cd reflex-fastapi-webhook-studio
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD to a long run of letters and digits.
docker compose up --build --detach
```

Open <http://localhost:17300>. Compose builds the image, runs the database migration once, then starts the app with
PostgreSQL and Redis. Run the same command again after you pull a new version. The
[deploy guide](docs/guide/deploy.md) covers TLS, other host names and the number of workers.

## Using it

### Make a bin

On the home page, type a label if you want one and press **New bin**. The bin's page opens and shows its URL, with
a **Copy URL** button, and when the bin expires. Give that URL to the service that sends the webhooks.

The home page lists the bins made in this browser, with how many requests each holds and when each expires. A bin
expires `WEBHOOK_STUDIO_BIN_TTL_DAYS` days (7 by default) after its last request, and is then deleted with all it
caught. To open a bin made elsewhere, paste its id, its URL or its page address into the **Open a bin** box.

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
| `200` and `{"ok": true, "request_id": "…"}`   | It stored the request, and you have not set its reply. A `HEAD` reply has no body. |
| The reply you set                             | It stored the request, and you set the bin's reply (see [Choose the reply](#choose-the-reply)). |
| `204`                                         | CORS is on and a browser sent a preflight. The preflight is stored too. |
| `404`                                         | No bin has this id. Nothing is stored.                                  |
| `405`                                         | The method is not one of the seven above. Nothing is stored.            |
| `413` and the `request_id`                    | The body is over the size cap. The request is stored without its body.  |

### Inspect requests

The bin's page lists its requests on the left, newest first. Each row shows the method in a colour of its own, the
path and how long ago it came. Click a row to see it on the right, in five tabs:

- **Overview:** the request id, time, method, path, query string, content type, body size, client address, HTTP
  version and the status sent back.
- **Headers:** every header in the order it reached the app. In Docker, Caddy changes some headers first; see
  [Limits and expiry](#limits-and-expiry). Headers that often hold secrets, such as `Authorization`,
  `Cookie` and names holding `token`, `secret`, `signature`, `api-key`, `password` or `session`, show as `••••` until
  you click them.
- **Query:** the raw query string, and each name and value in order.
- **Body:** JSON laid out with indents, form data as a table, other text as it came, and binary bodies as their size
  with a **Download** button for the exact bytes. The page never renders a body as HTML.
- **Replay:** send the request again to another URL; see [Replay a request](#replay-a-request).

### Find requests

Above the list, pick a method to show only requests with that method, or type in the search box to show only
requests whose method, path, query string, headers or first 4 KiB of body hold the text, in any case. The search
waits until you stop typing. A line under the boxes says how many requests match, and **Clear filters** shows them
all again.

The list loads 50 requests at a time. When you scroll near its end it loads the next 50, and a **Load older**
button does the same.

### Live updates

New requests appear at once, in every tab that has the bin open. Deletes show at once too. A dot at the top right
shows the state: **Live** (green) while the page follows the bin, **Connecting** (amber) while it connects or
reconnects, and **Offline** (red) when it cannot reach the server. After a reconnect the page reloads the bin, so it
misses nothing.

### Delete, clear and export

- **Delete request**, under the request on show, deletes that request.
- **Clear**, at the top, deletes every request in the bin. The bin keeps its URL and reply settings.
- **Delete bin** deletes the bin with all it caught, and takes you to the home page. The bin's URL stops working.
- **Export** downloads the bin and every request in it as one JSON file, oldest first. Bodies come as base64, and
  also as text when they are valid UTF-8.

Each delete asks first. Each kind of delete has its own **Don't ask again** box, which this browser remembers.

### Copy as curl

**Copy as curl** copies a command that sends the request on show to the bin again, with the same method, path,
query, headers and body bytes. Every value is quoted for the shell. A body that is not text goes through `base64`,
so its bytes survive.

### Choose the reply

**Reply settings** sets what the bin sends back to each sender: the status (200 to 599), the content type, extra
headers, the body, and a delay of up to `WEBHOOK_STUDIO_MAX_DELAY_MS` milliseconds (30 s by default). Leave **Custom
body** off to send the usual `{"ok": true, "request_id": "…"}`. **Use default** puts everything back.

The page shows each request before the delay ends, so you can watch a sender wait. A reply may not set
`Set-Cookie`, `Content-Security-Policy`, `Content-Length`, `Content-Type` (it has its own box),
`X-Content-Type-Options`, any `Access-Control-` header, or any header that belongs to one connection, such as
`Connection`. Header values may not hold line breaks.

### Replay a request

The **Replay** tab sends the request on show to a URL you type, with the same method, headers and body bytes. It
leaves out headers that belong to one connection, and `Host` and `Content-Length`, which follow from the new URL and
body. **Use original query string** adds the request's query to the URL. The tab shows the status, the time taken,
the headers and the first 64 KiB of the body. Nothing is stored.

A replay follows no redirects, gives up after `WEBHOOK_STUDIO_REPLAY_TIMEOUT_S` seconds (15 by default) and reads at
most 1 MiB. By default it may reach only public internet addresses, so it cannot reach this machine or a private
network. Set `WEBHOOK_STUDIO_REPLAY_MODE=local` to replay to services on your own machine.

### Use the REST API

The same data is open to scripts. Make a bin, then list and read what it caught:

```bash
BASE=http://localhost:17301
curl -s -X POST $BASE/api/v1/bins -H 'content-type: application/json' -d '{"label": "GitHub"}'
BIN=h-xohSG6xKnGPzKOrb_JVg   # the id from the reply
curl -s "$BASE/api/v1/bins/$BIN/requests?limit=10"
curl -s "$BASE/api/v1/bins/$BIN/requests?method=POST&q=invoice"
curl -s $BASE/api/v1/bins/$BIN/requests/01a137d3-3e85-702c-be8d-84cdcc0283f7
```

A request reply holds the headers and query as lists of name and value pairs, in the order they reached the app.
The body is in `body_base64`, and also in `body_text` when it is valid UTF-8. To read the next page, pass the id of
the last request you got as `before`. To rename a bin, send `PATCH $BASE/api/v1/bins/$BIN` with
`{"label": "Stripe"}`, or `{"label": null}` to clear the label; an open page shows the new label at once.

To set the bin's reply, send the whole reply in a `PATCH`; `{"reply": null}` puts back the default:

```bash
curl -s -X PATCH $BASE/api/v1/bins/$BIN -H 'content-type: application/json' \
  -d '{"reply": {"status": 418, "headers": [["X-Tea", "yes"]], "body": "short and stout", "delay_ms": 500}}'
```

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
| `WEBHOOK_STUDIO_BIN_TTL_DAYS`         | `7`                                          | Days a bin lives after its last request.                   |
| `WEBHOOK_STUDIO_SWEEP_INTERVAL_S`     | `3600`                                       | Seconds between deletes of expired bins.                   |
| `WEBHOOK_STUDIO_BIN_LISTING`          | `browser`                                    | Which bins the home page lists: `browser` for the ones made in this browser, `all` for every bin. |
| `WEBHOOK_STUDIO_MAX_DELAY_MS`         | `30000`                                      | Longest reply delay a bin may set, in milliseconds.        |
| `WEBHOOK_STUDIO_REPLAY_MODE`          | `restricted`                                 | `restricted`: replays reach public internet addresses only. `local`: any address, this machine included. |
| `WEBHOOK_STUDIO_REPLAY_TIMEOUT_S`     | `15`                                         | Seconds a replay may take in all.                          |
| `WEBHOOK_STUDIO_PUBLIC_BASE_URL`      | unset                                        | The scheme and host senders use, such as `https://hooks.example.com`, when the app runs behind a proxy. Capture URLs and curl commands use it. |
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

Docker Compose reads a few more values from `.env`: `POSTGRES_PASSWORD` (required), `APP_URL` (the address people
open), `APP_BIND` and `APP_PORT` (where Compose publishes the app) and `GRANIAN_WORKERS`. The
[deploy guide](docs/guide/deploy.md) explains each one.

## REST API

| Method | Path                                          | Purpose                                         |
| ------ | --------------------------------------------- | ----------------------------------------------- |
| any    | `/api/webhook/{bin_id}` and any path under it | Catch a request                                 |
| POST   | `/api/v1/bins`                                | Create a bin, with an optional label. Returns `201`. |
| GET    | `/api/v1/bins`                                | List every bin with its request count. Only when `WEBHOOK_STUDIO_BIN_LISTING` is `all`; otherwise `404`. |
| GET    | `/api/v1/bins/{bin_id}`                       | Read a bin and its reply settings               |
| PATCH  | `/api/v1/bins/{bin_id}`                       | Change the label or the reply; leave a field out to keep it |
| DELETE | `/api/v1/bins/{bin_id}`                       | Delete the bin and its requests. Returns `204`. |
| GET    | `/api/v1/bins/{bin_id}/export`                | Download the bin and its requests as one JSON file |
| GET    | `/api/v1/bins/{bin_id}/requests`              | List requests, newest first: `method`, `q` (up to 200 characters), `before` (a request id), `limit` 1 to 100 (50 if left out) |
| DELETE | `/api/v1/bins/{bin_id}/requests`              | Delete every request. Returns `204`.            |
| GET    | `/api/v1/bins/{bin_id}/requests/{request_id}` | Read one request in full                        |
| DELETE | `/api/v1/bins/{bin_id}/requests/{request_id}` | Delete one request. Returns `204`.              |
| GET    | `/api/v1/bins/{bin_id}/requests/{request_id}/curl` | The request as a curl command, as plain text |
| POST   | `/api/v1/bins/{bin_id}/requests/{request_id}/replay` | Send the request to `target_url`; set `use_original_query` to `false` to leave its query out |
| GET    | `/api/v1/health`                              | Check that the app, its database and Redis, when used, answer |
| GET    | `/api/v1/version`                             | Read the app's version                         |

`GET /api/v1/health` returns `{"status": "ok", "version": "<app version>", "database": "ok"}`, with `"redis": "ok"`
added when the app uses Redis. It returns `503`, naming the failed check, if the database or Redis does not answer.
`GET /api/v1/version` returns `{"version": "<app version>"}` and checks nothing else, so it answers even then. Each
page shows the same version beside the app's name.

Errors come as [problem details](https://www.rfc-editor.org/rfc/rfc9457) with the type
`application/problem+json`. A reply setting that breaks a rule, or a replay target that is not an `http` or `https`
URL, gets `422`; a replay the mode does not allow gets `403`; a replay target that does not answer gets `502`. The
app serves its OpenAPI page at `/api/docs` and the schema at `/api/openapi.json`.

## Limits and expiry

- A body over `WEBHOOK_STUDIO_MAX_BODY_BYTES` (1 MiB by default) is not stored. The app stops reading it at the cap,
  replies `413`, and stores the request with `body_truncated` set and no body.
- A bin keeps its newest `WEBHOOK_STUDIO_MAX_REQUESTS_PER_BIN` requests (500 by default).
- The app holds at most `WEBHOOK_STUDIO_MAX_BINS` bins (1000 by default). Creating one more gets `409`.
- A bin is deleted, with its requests, `WEBHOOK_STUDIO_BIN_TTL_DAYS` days (7 by default) after its last request.
  Each worker checks every `WEBHOOK_STUDIO_SWEEP_INTERVAL_S` seconds (an hour by default).
- A label is 1 to 80 characters, and a search up to 200.
- A reply body is at most 64 KiB, with at most 32 extra headers, each value up to 4 KiB.
- A replay reads at most 1 MiB of the reply, and the page shows the first 64 KiB.
- PostgreSQL cannot store the NUL character in text, so the app shows it as U+FFFD in the stored path, query, headers
  and content type. The stored body is always exact.
- A request's `content_type` holds at most 255 characters of its `Content-Type`; its headers keep the whole value.
- In Docker, the Caddy inside the image changes the headers before the app stores them. It groups them by name,
  though values of one name keep their order, drops hop-by-hop headers such as `Connection`, and adds `Via`,
  `X-Forwarded-*` and sometimes `Accept-Encoding`. The [deploy guide](docs/guide/deploy.md#what-to-know) has the
  details. Run the app without Docker to store headers exactly as sent.

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
  network. The [deploy guide](docs/guide/deploy.md) shows how.
- Replays reach only public internet addresses unless you set `WEBHOOK_STUDIO_REPLAY_MODE=local`. The app checks
  the address as the connection opens, so a name that points somewhere else on a second lookup cannot get past it.
- In Docker, the app's own websocket and pages accept only the origin in `APP_URL`, so another website cannot drive
  them from a visitor's browser.
- Behind a proxy on the same machine, such as the Caddy inside the Docker image, the app takes the sender's address
  from the last `X-Forwarded-For` entry. From any other peer it ignores that header.
- The Docker image runs as a user without root rights, and holds no pip, bun or `node_modules`.
- Logs never hold bodies or header values, and show only the first 6 characters of a bin id.

## How it works

### Context

![Context](docs/diagrams/01-c4-context.png)

Senders send requests to bins. Developers use the pages or the REST API, and may replay a request to another
service.

### Containers

![Containers](docs/diagrams/02-c4-container.png)

Reflex turns the Python UI into a React app that runs in the browser. Each worker process runs the API and the Reflex
backend, and keeps data in SQLite or PostgreSQL. With Redis, several workers share page state and live updates. In
Docker, Caddy serves the built pages and passes the rest to the workers.

### Data model

![Data model](docs/diagrams/03-data-model.png)

A bin has many captured requests. Deleting a bin deletes its requests.

### Capturing a request

![Capturing a request](docs/diagrams/04-seq-capture.png)

The capture route looks up the bin's reply, then stores the request, drops the oldest past the cap and updates the
bin, all in one transaction. It publishes the event, waits the bin's delay, and sends the bin's reply.

### Live push

![Live push](docs/diagrams/05-seq-live-push.png)

Each open bin page runs one watch task. It subscribes, reloads, then applies each event (a new request, a delete, a
clear or an edit) and checks every 15 s that its tab is still open. With Redis, every worker hears every event.

### Deployment

![Deployment](docs/diagrams/06-deployment.png)

Dev mode runs a frontend dev server on port 17300 and the backend on port 17301. Production mode serves everything
from one process on port 17300. Docker Compose runs the app, a one-shot migration, PostgreSQL and Redis, and
publishes port 17300 on `127.0.0.1` only.

## Links

- [Docs site](https://nikhil-raphy.github.io/reflex-fastapi-webhook-studio/)
- [Browser tests](https://github.com/Nikhil-Raphy/playwright-e2e-tests-webhook-studio): Playwright tests in
  Chromium, Firefox and WebKit, including WCAG 2.2 AA accessibility scans. CI runs them against every change.
- [Decision records](docs/adr/index.md)

## Contributions

This is a personal project. It takes no code contributions for now, but you may open an issue to report a bug or ask
for a feature.

## License

[Apache-2.0](LICENSE). Copyright 2026 Nikhil-Raphy.
