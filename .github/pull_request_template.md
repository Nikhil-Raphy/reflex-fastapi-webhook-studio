## What this changes

<!-- Say what the change does and why. -->

## Checks

- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run pylint --recursive=y reflex_fastapi_webhook_studio tests rxconfig.py alembic` and `uv run mypy .` pass.
- [ ] `uv run pytest --cov` passes with at least 90% coverage, on SQLite and on PostgreSQL
      (`WEBHOOK_STUDIO_TEST_DATABASE_URL` set).
- [ ] A schema change comes with an Alembic migration that upgrades and downgrades.
- [ ] Each new test follows Given / When / Then.
- [ ] Docs describe only what this change builds.

## Diagrams changed

<!-- List each `.puml` file under docs/diagrams/ that this pull request adds or changes, so the maintainer can render it again. Write "None" if there are none. -->
