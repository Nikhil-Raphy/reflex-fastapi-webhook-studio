"""Shared pytest fixtures."""

# Fixtures take other fixtures as arguments of the same name.
# pylint: disable=redefined-outer-name

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config

from reflex_fastapi_webhook_studio.db.engine import Database

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"
TEST_DATABASE_URL = "WEBHOOK_STUDIO_TEST_DATABASE_URL"


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio only.

    Returns:
        The name of the anyio backend.
    """
    return "asyncio"


def migrate(url: str, *, to: str) -> None:
    """Run the Alembic migrations up or down against a database.

    Args:
        url: The async database URL.
        to: "head" to create every table, or "base" to drop them.
    """
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    if to == "base":
        command.downgrade(config, "base")
    else:
        command.upgrade(config, to)


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def database_url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    """Give each test an empty database at the latest schema, on SQLite and, when set up, on PostgreSQL.

    Args:
        request: The pytest request, whose param names the engine.
        tmp_path: A folder for the SQLite file.

    Returns:
        The database URL.
    """
    if request.param == "sqlite":
        url = f"sqlite+aiosqlite:///{tmp_path / 'studio.db'}"
    else:
        url = os.environ.get(TEST_DATABASE_URL, "")
        if not url:
            pytest.skip(f"{TEST_DATABASE_URL} is not set")
        migrate(url, to="base")
    migrate(url, to="head")
    return url


@pytest.fixture
async def database(database_url: str) -> AsyncIterator[Database]:
    """Open the test database.

    Args:
        database_url: The URL of the migrated test database.

    Yields:
        The database.
    """
    db = Database(database_url)
    yield db
    await db.engine.dispose()
