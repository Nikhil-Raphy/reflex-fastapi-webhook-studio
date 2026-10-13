"""Tests for the Reflex app that mounts the API."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from reflex_fastapi_webhook_studio import __version__
from reflex_fastapi_webhook_studio.reflex_fastapi_webhook_studio import app


@pytest.mark.anyio
async def test_given_reflex_app_when_health_is_requested_then_mounted_api_replies() -> None:
    """Given the Reflex app, when a client asks the API it mounts for health, then it replies 200 with the version."""
    # Given
    api = app.api_transformer
    assert isinstance(api, FastAPI)
    # When
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    # Then
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
