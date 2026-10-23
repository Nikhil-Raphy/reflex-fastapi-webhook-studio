"""Tests for the app entry: the API goes ahead of Reflex."""

import inspect
from typing import TYPE_CHECKING

import pytest
import reflex as rx
from httpx import ASGITransport, AsyncClient
from starlette.responses import PlainTextResponse

from reflex_fastapi_webhook_studio.reflex_fastapi_webhook_studio import app

if TYPE_CHECKING:
    from starlette.types import Receive, Scope, Send


async def fake_reflex(scope: Scope, receive: Receive, send: Send) -> None:
    """Stand in for Reflex's ASGI app.

    Args:
        scope: The ASGI scope.
        receive: The ASGI receive channel.
        send: The ASGI send channel.
    """
    await PlainTextResponse("reflex")(scope, receive, send)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "served_by_api"),
    [("/api/nope", True), ("/api", True), ("/api/v1/bins/bad", True), ("/apiary", False), ("/", False)],
)
async def test_given_studio_app_when_path_is_requested_then_api_paths_skip_reflex(
    monkeypatch: pytest.MonkeyPatch, path: str, *, served_by_api: bool
) -> None:
    """Given the app entry, when a path is requested, then paths under /api reach the API and the rest reach Reflex."""
    # Given
    monkeypatch.setattr(rx.App, "__call__", lambda _self: fake_reflex)
    asgi = app()
    # When
    async with AsyncClient(transport=ASGITransport(app=asgi), base_url="http://test") as client:
        response = await client.get(path, headers={"origin": "https://any.example"})
    # Then
    assert (response.text != "reflex") is served_by_api
    assert "access-control-allow-origin" not in response.headers


def test_given_studio_app_when_reflex_reads_lifespan_tasks_then_each_signature_resolves() -> None:
    """Given the app entry, when Reflex reads each lifespan task's signature at start-up, then every name resolves."""
    # Given
    tasks = app.get_lifespan_tasks()
    # When
    signatures = [inspect.signature(task) for task in tasks if callable(task)]
    # Then
    assert signatures
