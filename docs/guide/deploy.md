# Deploy with Docker

Docker Compose runs the app for a team: four services on one machine.

| Service    | What it does                                                                                  |
| ---------- | --------------------------------------------------------------------------------------------- |
| `app`      | The app on one port, 17300. Caddy inside the image serves the pages and passes the API, the websocket and Reflex's own routes to the backend workers. |
| `migrate`  | Runs `alembic upgrade head` once. `app` starts only after it ends well.                        |
| `postgres` | PostgreSQL 18, with its data in the `postgres-data` volume.                                    |
| `redis`    | Redis 8. It holds each browser tab's page state and carries live updates between workers.     |

Each image is pinned by digest. The app's image is built on your machine; nothing is pulled from a registry for it.

## Start it

```bash
git clone https://github.com/Nikhil-Raphy/reflex-fastapi-webhook-studio.git
cd reflex-fastapi-webhook-studio
cp .env.example .env
```

Edit `.env`. These values are for Compose:

| Value               | Default                  | Meaning                                                                         |
| ------------------- | ------------------------ | ------------------------------------------------------------------------------- |
| `POSTGRES_PASSWORD` | none; required           | Password of the database. Use letters and digits only, since it goes into a URL. |
| `APP_URL`           | `http://localhost:17300` | The address people open in a browser. The pages are built with it, so rebuild after a change. |
| `APP_BIND`          | `127.0.0.1`              | The host address Compose publishes the app on. The default keeps it on this machine. |
| `APP_PORT`          | `17300`                  | The host port. If you change it, change the port in `APP_URL` to match.         |
| `GRANIAN_WORKERS`   | Reflex's own count       | How many backend workers run. Reflex picks a number from the CPU count.         |

The app's own settings, such as `WEBHOOK_STUDIO_REPLAY_MODE`, go in the same file; see
[Configuration](configuration.md). Compose sets the database and Redis URLs itself.

Then build and start:

```bash
docker compose up --build --detach
docker compose ps
curl http://localhost:17300/api/v1/health
```

The health check answers `{"status": "ok", ..., "database": "ok", "redis": "ok"}` once all is well. See the logs with
`docker compose logs app`.

## Upgrade

```bash
git pull
docker compose up --build --detach
```

Compose builds the new image, runs any new migration, then restarts the app.

## Put a proxy in front

Run a reverse proxy that handles TLS, and leave the app on `127.0.0.1`. The proxy must pass websocket upgrades,
since each page keeps a websocket open on `/_event`.

Keep the pages and `/api/v1` on a private network, and expose only `/api/webhook/*` to the internet. One way is two
host names on the proxy: a public one for senders that passes only capture paths, and a private one for your team.
Set `APP_URL` to the private address and `WEBHOOK_STUDIO_PUBLIC_BASE_URL` to the public one, so the pages show
capture URLs that senders can reach. A private DNS name is not enough: anyone who reaches the proxy can ask for that
host, so the private site must refuse outside addresses itself.

With [Caddy](https://caddyserver.com) on the host, which handles TLS and websockets by itself:

```text
hooks.example.com {
	@capture path /api/webhook/*
	handle @capture {
		reverse_proxy 127.0.0.1:17300
	}
	respond 404
}

studio.internal.example.com {
	@outside not remote_ip private_ranges
	respond @outside 403
	reverse_proxy 127.0.0.1:17300
}
```

`private_ranges` covers the `10.`, `172.16.`, `192.168.` and loopback ranges and their IPv6 forms. If your VPN uses
other addresses, such as Tailscale's `100.64.0.0/10`, add them after `private_ranges`.

With nginx, the websocket needs its own lines:

```nginx
location /_event {
    proxy_pass http://127.0.0.1:17300;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 1h;
}
```

and in `.env`:

```bash
APP_URL=https://studio.internal.example.com
WEBHOOK_STUDIO_PUBLIC_BASE_URL=https://hooks.example.com
```

Then run `docker compose up --build --detach` again, since the pages are built with `APP_URL`.

## What to know

- The app's websocket and pages accept only the origin in `APP_URL`. A page opened at any other address cannot
  connect.
- Behind another proxy, the stored client address of each request is that proxy's address, not the sender's.
- The Caddy inside the image changes each request's headers before the app stores them. It groups headers by name,
  though values of one name keep their order. It drops hop-by-hop headers, such as `Connection` and the headers it
  names. It adds `Via`, and sets `X-Forwarded-For`, `X-Forwarded-Host` and `X-Forwarded-Proto` in place of any the
  sender sent. It adds `Accept-Encoding: gzip` when the sender sent no `Accept-Encoding`. A proxy in front makes its
  own changes. To store headers exactly as sent, run the app without Docker and with no proxy in front.
- Back up the database with `docker compose exec postgres pg_dump -U studio studio > backup.sql`.
- `docker compose down` stops everything and keeps the data. `docker compose down --volumes` deletes the data too.
