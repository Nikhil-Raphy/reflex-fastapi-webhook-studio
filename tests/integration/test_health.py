"""Tests for the health route."""

import pytest
from httpx import ASGITransport, AsyncClient

from reflex_fastapi_webhook_studio import __version__
from reflex_fastapi_webhook_studio.api.app import create_api


@pytest.mark.anyio
async def test_given_api_when_health_is_requested_then_status_is_ok_with_version() -> None:
    """Given the API, when a client asks for health, then the reply is 200 with status ok and the app version."""
    # Given
    transport = ASGITransport(app=create_api())
    # When
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    # Then
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
