# ADR-0005: Replay modes and the address guard

## Status

Accepted

## Context

Replay makes the server send a stored request to a URL the user types. On a shared server that would let users
reach internal hosts and cloud metadata addresses, such as `169.254.169.254`. Someone running the app on a laptop
needs replay to reach `localhost`. Checking the URL before sending is not enough, because a DNS name can point to a
public address when checked and a private one when the socket opens.

## Decision

- The server sets the mode with `WEBHOOK_STUDIO_REPLAY_MODE`: `restricted` (the default) or `local`.
- Both modes allow only `http` and `https` URLs with a host and no user name. Replays follow no redirects, give up
  after `WEBHOOK_STUDIO_REPLAY_TIMEOUT_S` seconds (15 by default) and read at most 1 MiB of the reply.
- The replay service calls httpcore directly, with `httpx.create_ssl_context()` for TLS. httpcore follows no
  redirects and reads no proxy settings from the environment.
- In `restricted` mode, `GuardedBackend` in `security/ssrf.py` wraps httpcore's network backend. When httpcore opens
  a connection, it looks the host up once, refuses unless every address is on the public internet, and then
  connects to an address it checked. IPv6 forms that hold an IPv4 address (mapped, 6to4 and Teredo) are judged by
  the IPv4 address too. Unix sockets are always refused.
- httpcore still passes the host name to TLS, so SNI and the certificate check use the name, not the address.
- `local` mode uses httpcore's own backend, with no address check.
- Outbound headers leave out hop-by-hop headers (RFC 9110, section 7.6.1), any header the `Connection` header
  names, `Host` and `Content-Length`. The method and the body bytes stay as stored.
- The result is shown once and never stored.

## Consequences

- The default is safe on a shared server, with no extra package.
- The check happens when the socket opens, so a name that changes its address between lookups gets nowhere.
- A blocked target gets `403` from the API; a bad URL gets `422`; a target that does not answer gets `502`.
- In `local` mode anyone who can open the pages can make the server reach its own network, so use it only where you
  trust them.
