"""Tests for the health route."""

from typing import TYPE_CHECKING

import pytest

from reflex_fastapi_webhook_studio import __version__
from reflex_fastapi_webhook_studio.db.engine import Database
from tests.factories import api_client

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.anyio
async def test_given_working_database_when_health_is_requested_then_ok_with_version(database: Database) -> None:
    """Given a working database, when a client asks for health, then it gets 200 with status, version and database."""
    # Given
    async with api_client(database) as client:
        # When
        response = await client.get("/api/v1/health")
    # Then
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "database": "ok"}


@pytest.mark.anyio
async def test_given_broken_database_when_health_is_requested_then_503_problem(tmp_path: Path) -> None:
    """Given a database that cannot open, when a client asks for health, then the reply is 503 naming the check."""
    # Given
    broken = Database(f"sqlite+aiosqlite:///{tmp_path / 'missing' / 'studio.db'}")
    async with api_client(broken) as client:
        # When
        response = await client.get("/api/v1/health")
    # Then
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["check"] == "database"
    await broken.engine.dispose()
