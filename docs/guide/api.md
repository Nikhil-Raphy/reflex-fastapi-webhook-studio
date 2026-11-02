# REST API

Scripts get the same data as the pages. The examples use dev mode, where the API is on port 17301; in production
mode and in Docker, use port 17300. The app serves its OpenAPI page at `/api/docs` and the schema at
`/api/openapi.json`.

## Routes

| Method | Path                                          | Purpose                                         |
| ------ | --------------------------------------------- | ----------------------------------------------- |
| any    | `/api/webhook/{bin_id}` and any path under it | Catch a request                                 |
| POST   | `/api/v1/bins`                                | Create a bin, with an optional label. Returns `201`. |
| GET    | `/api/v1/bins`                                | List every bin with its request count. Only when `WEBHOOK_STUDIO_BIN_LISTING` is `all`; otherwise `404`. |
| GET    | `/api/v1/bins/{bin_id}`                       | Read a bin and its reply settings               |
| PATCH  | `/api/v1/bins/{bin_id}`                       | Change the label or the reply; leave a field out to keep it |
| DELETE | `/api/v1/bins/{bin_id}`                       | Delete the bin and its requests. Returns `204`. |
| GET    | `/api/v1/bins/{bin_id}/export`                | Download the bin and its requests as one JSON file |
| GET    | `/api/v1/bins/{bin_id}/requests`              | List requests, newest first                     |
| DELETE | `/api/v1/bins/{bin_id}/requests`              | Delete every request. Returns `204`.            |
| GET    | `/api/v1/bins/{bin_id}/requests/{request_id}` | Read one request in full                        |
| DELETE | `/api/v1/bins/{bin_id}/requests/{request_id}` | Delete one request. Returns `204`.              |
| GET    | `/api/v1/bins/{bin_id}/requests/{request_id}/curl` | The request as a curl command, as plain text |
| POST   | `/api/v1/bins/{bin_id}/requests/{request_id}/replay` | Send the request to another URL           |
| GET    | `/api/v1/health`                              | Check that the app, its database and Redis, when used, answer |

Request routes sit under their bin, so you need the bin's id to read or change a request.

## Catch requests

The bin takes `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE` and `OPTIONS`, and stores whatever follows the bin id
as the path.

```bash
BASE=http://localhost:17301
curl -s -X POST $BASE/api/v1/bins -H 'content-type: application/json' -d '{"label": "GitHub"}'
BIN=<the id from the reply>
curl -s -X POST $BASE/api/webhook/$BIN -H 'content-type: application/json' -d '{"event": "push"}'
curl -s -X POST $BASE/api/webhook/$BIN/forms -d 'name=Ada&lang=python'
curl -s "$BASE/api/webhook/$BIN/search?tag=a&tag=b"
```

| The bin replies with                          | When                                                                    |
| --------------------------------------------- | ----------------------------------------------------------------------- |
| `200` and `{"ok": true, "request_id": "…"}`   | It stored the request, and the bin's reply is not set. A `HEAD` reply has no body. |
| The bin's reply                               | It stored the request, and the bin's reply is set.                      |
| `204`                                         | CORS is on and a browser sent a preflight. The preflight is stored too. |
| `404`                                         | No bin has this id. Nothing is stored.                                  |
| `405`                                         | The method is not one of the seven above. Nothing is stored.            |
| `413` and the `request_id`                    | The body is over the size cap. The request is stored without its body.  |

## Read requests

`GET /api/v1/bins/{bin_id}/requests` takes:

| Parameter | Meaning                                                                                  |
| --------- | ---------------------------------------------------------------------------------------- |
| `method`  | Only requests with this method                                                           |
| `q`       | Only requests whose method, path, query string, headers or first 4 KiB of body hold this text, in any case; up to 200 characters |
| `before`  | Only requests older than the one with this id. Pass the last id of a page to get the next. |
| `limit`   | 1 to 100; 50 if left out                                                                 |

```bash
curl -s "$BASE/api/v1/bins/$BIN/requests?method=POST&q=invoice&limit=10"
curl -s $BASE/api/v1/bins/$BIN/requests/<request id>
curl -s $BASE/api/v1/bins/$BIN/requests/<request id>/curl
```

A request holds its headers and query as lists of name and value pairs, in the order they reached the app. In Docker,
Caddy changes some headers first; see [What to know](deploy.md#what-to-know). The body is in `body_base64`, and also
in `body_text` when it is valid UTF-8.

## Set the reply

`PATCH /api/v1/bins/{bin_id}` with a `reply` sets the whole reply; a field left out of the reply takes its default.
`{"reply": null}` puts back the default, and `{"label": null}` clears the label.

```bash
curl -s -X PATCH $BASE/api/v1/bins/$BIN -H 'content-type: application/json' \
  -d '{"reply": {"status": 418, "content_type": "text/plain", "headers": [["X-Tea", "yes"]],
       "body": "short and stout", "delay_ms": 500}}'
```

| Field          | Default | Rule                                                                              |
| -------------- | ------- | --------------------------------------------------------------------------------- |
| `status`       | `200`   | 200 to 599. A 204, 205 or 304 reply has no body.                                  |
| `content_type` | `null`  | Up to 255 characters, no line break                                               |
| `headers`      | `[]`    | Up to 32 pairs. Names must be RFC 9110 tokens; values up to 4 KiB with no line break. No `Set-Cookie`, `Content-Security-Policy`, `Content-Length`, `Content-Type`, `X-Content-Type-Options`, `Access-Control-*` or hop-by-hop headers. |
| `body`         | `null`  | Up to 64 KiB. `null` sends the default JSON body with the request id.             |
| `delay_ms`     | `0`     | 0 to `WEBHOOK_STUDIO_MAX_DELAY_MS`                                                |

A reply that breaks a rule gets `422`, and nothing changes.

## Replay a request

```bash
curl -s -X POST $BASE/api/v1/bins/$BIN/requests/<request id>/replay \
  -H 'content-type: application/json' -d '{"target_url": "https://example.com/hook", "use_original_query": true}'
```

The reply holds `status`, `reason`, `elapsed_ms`, `headers`, `body_base64`, `body_text` (when UTF-8) and
`body_truncated`. A replay follows no redirects and reads at most 1 MiB. A target that is not an `http` or `https`
URL gets `422`; one the replay mode does not allow gets `403`; one that does not answer in time, or at all, gets
`502`.

## Export

`GET /api/v1/bins/{bin_id}/export` downloads one JSON file:

```json
{
  "format": "webhook-studio-export",
  "version": 1,
  "exported_at": "2026-10-30T09:30:00Z",
  "bin": {"id": "…", "label": "…", "created_at": "…", "last_activity_at": "…", "expires_at": "…",
          "reply": {"status": 200, "content_type": null, "headers": [], "body": null, "delay_ms": 0}},
  "requests": [
    {"id": "…", "received_at": "…", "method": "POST", "path": "/github", "query_string": "",
     "query_params": [], "headers": [["content-type", "application/json"]], "body_base64": "…",
     "body_size": 18, "body_truncated": false, "content_type": "application/json", "remote_addr": "…",
     "http_version": "1.1", "reply_status": 200, "body_text": "{\"event\": \"push\"}"}
  ]
}
```

Requests come oldest first. `body_text` appears only when the body is valid UTF-8.

## Errors

Errors come as [problem details](https://www.rfc-editor.org/rfc/rfc9457) with the type
`application/problem+json`. `GET /api/v1/health` returns `503`, naming the failed check, if the database or Redis
does not answer.
