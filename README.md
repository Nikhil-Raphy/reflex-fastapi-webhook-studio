# Reflex FastAPI Webhook Studio

Catch, inspect and replay webhooks and HTTP requests.

## What it does

This version is the base of the app. It runs a [Reflex](https://reflex.dev) web app with a
[FastAPI](https://fastapi.tiangolo.com) app mounted inside it, in one Python process. It serves:

- a home page, the Reflex blank page;
- a health check at `GET /api/v1/health`, which returns `{"status": "ok", "version": "<app version>"}`.

## Quick start

You need [uv](https://docs.astral.sh/uv/). uv fetches Python 3.14 for you.

```bash
git clone https://github.com/Nikhil-Raphy/reflex-fastapi-webhook-studio.git
cd reflex-fastapi-webhook-studio
uv sync
uv run reflex run
```

Open <http://localhost:17300> for the home page. In this dev mode the API runs on a second port, so the health check
is at <http://localhost:17301/api/v1/health>.

To serve both on one port, run the production build. Production mode needs the backend on the same port as the page:

```bash
uv run reflex run --env prod --backend-port 17300
```

Then the home page is at <http://localhost:17300> and the health check at <http://localhost:17300/api/v1/health>.

## How it works

### Containers

![Containers](docs/diagrams/03-c4-container.png)

Reflex turns the Python UI into a React app that runs in the browser. One worker process runs the Reflex backend and
the FastAPI app.

### Components

![Components](docs/diagrams/04-c4-component.png)

The app module builds the Reflex app and mounts the FastAPI app that `create_api()` returns.

### Deployment

![Deployment](docs/diagrams/15-deployment.png)

Dev mode runs a frontend dev server on port 17300 and the backend on port 17301. Production mode serves everything
from one process on port 17300.

### CI, docs and releases

![CI, docs and releases](docs/diagrams/16-activity-ci.png)

Each pull request runs lint, tests and a scan of the locked packages for known flaws. Each push to `main` also builds
the docs site and updates the release pull request.

## Links

- [Docs site](https://nikhil-raphy.github.io/reflex-fastapi-webhook-studio/)
- [Decision records](docs/adr/index.md)

## Contributions

This is a personal project. It takes no code contributions for now, but you may open an issue to report a bug or ask
for a feature.

## License

[Apache-2.0](LICENSE). Copyright 2026 Nikhil-Raphy.
