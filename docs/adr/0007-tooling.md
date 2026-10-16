# ADR-0007: Tooling — uv, Ruff, pylint, mypy, pytest

## Status

Accepted

## Context

The code must follow PEP 8 and pass Ruff, isort-style import sorting, Black-style formatting and pylint, with a line
length of 120. It needs strict typing and as few tools as possible.

## Decision

- **Packaging:** `uv` with the `uv_build` backend, a flat layout (`module-root = ""`, as Reflex expects), Python
  3.14 pinned in `.python-version` and a committed `uv.lock`.
- **Lint and format:** Ruff with `select = ["ALL"]`. Ruff's isort rules sort imports and its formatter writes Black
  style, so we do not run isort or Black on their own.
- **Second linter:** pylint. Each message we turn off carries a reason in `pyproject.toml`.
- **Types:** `mypy --strict` with the Pydantic plugin.
- **Tests:** pytest with the anyio plugin and `pytest-cov`. Lines and branches together must reach 90% coverage.
  Test names and `# Given` / `# When` / `# Then` blocks carry the Gherkin form, not `.feature` files.
- **Hooks:** pre-commit runs Ruff, `uv lock`, mypy, pylint, file checks and a Conventional Commits check.

## Consequences

- Fewer tools to install and pin.
- Ruff's import order and format match isort and Black in their default profiles.
- `uv build` packs the flat `reflex_fastapi_webhook_studio/` package into the wheel and sdist, and Reflex finds the
  app through `rxconfig.py` in both dev and production mode.
- Every compiled dependency (granian, pydantic-core, psycopg-binary, greenlet) ships a CPython 3.14 wheel, and Ruff,
  pylint and mypy all target Python 3.14.
- Reflex's component packages (`reflex_components_*`) ship no `py.typed` marker, so mypy would type every component
  as `Any`. A `[[tool.mypy.overrides]]` entry sets `follow_untyped_imports = true` for them, and mypy reads their
  real types.
- One Reflex stub flaw remains: it types `rx.color_mode` as a `Var`, so `rx.color_mode.button` carries a
  `# type: ignore[attr-defined]`. With that, `mypy --strict` passes on the Reflex page code.
- Ruff moves imports that serve only type hints under `TYPE_CHECKING`, but FastAPI, Pydantic and Reflex read some
  type hints at run time. `pyproject.toml` marks SQLModel and Pydantic models and dataclasses as read at run time.
  Other imports that a framework reads, such as the types in a route's signature, carry a `noqa` with the reason.
- The migrations live in `alembic/`, the same name as the library. Ruff and pylint treat `alembic` as a third-party
  package, and pylint runs with `--recursive=y` so it checks the migrations too.
- The table, domain and API layers repeat field lists, so pylint flags copied blocks only from 8 lines up.
