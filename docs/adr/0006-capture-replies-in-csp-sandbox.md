# ADR-0006: Capture replies run in a CSP sandbox

## Status

Accepted

## Context

The capture routes under `/api/webhook/` answer anyone who has a bin's URL, from the same origin as the app's pages.
A browser that opens a capture URL must never run content from that reply with the app's origin, or a script there
could read the app's storage and cookies. The inspector shows what senders sent, so it must never run that either.

## Decision

- Every reply from `/api/webhook/*` carries `Content-Security-Policy: sandbox` and `X-Content-Type-Options: nosniff`,
  whatever its status. One ASGI layer, `CaptureReplyHeaders`, adds them, so they also reach replies that the capture
  handler never builds, such as a `405`.
- When `WEBHOOK_STUDIO_CORS_ENABLED` is `true`, capture replies also carry `Access-Control-Allow-Origin: *`, never
  with credentials. The management API under `/api/v1` sends no CORS headers.
- The inspector never renders captured content as HTML. It shows bodies, headers and query values as text or in a
  code block, which React escapes.

## Consequences

- Browsers treat a capture reply as coming from an opaque origin, so a script there cannot touch the app's storage
  or cookies.
- Browsers do not guess a content type for a capture reply.
- Servers that send webhooks ignore these headers, so webhooks work as before.
