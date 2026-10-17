"""Builders for domain values and API clients in tests."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid7

from httpx import ASGITransport, AsyncClient

from reflex_fastapi_webhook_studio.api.app import create_api
from reflex_fastapi_webhook_studio.domain import Bin, CapturedRequest, HttpMethod, body_preview, new_bin_id
from reflex_fastapi_webhook_studio.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from redis.asyncio import Redis

    from reflex_fastapi_webhook_studio.db.engine import Database

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@asynccontextmanager
async def api_client(
    database: Database, settings: Settings | None = None, *, redis: Redis | None = None
) -> AsyncIterator[AsyncClient]:
    """Open an HTTP client that calls the FastAPI app in process.

    Args:
        database: The test database.
        settings: The settings; the defaults when None.
        redis: A Redis client for health to check, if any.

    Yields:
        The client.
    """
    api = create_api(settings or Settings(), database, redis=redis)
    transport = ASGITransport(app=api, client=("203.0.113.7", 50000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def make_bin(*, label: str | None = "orders", at: datetime = NOW) -> Bin:
    """Build a bin made at the given time, expiring seven days later.

    Args:
        label: The bin label.
        at: When the bin was made.

    Returns:
        The bin.
    """
    return Bin(id=new_bin_id(), label=label, created_at=at, last_activity_at=at, expires_at=at + timedelta(days=7))


def make_request(bin_id: str, *, body: bytes = b'{"a": 1}', at: datetime = NOW) -> CapturedRequest:
    """Build a captured POST request with a JSON body.

    Args:
        bin_id: The bin that caught it.
        body: The body bytes.
        at: When it arrived.

    Returns:
        The request.
    """
    return CapturedRequest(
        id=uuid7(),
        bin_id=bin_id,
        received_at=at,
        method=HttpMethod.POST,
        path="/github",
        query_string="x=1&x=2",
        query_params=(("x", "1"), ("x", "2")),
        headers=(("content-type", "application/json"), ("x-b", "2"), ("x-a", "1"), ("x-b", "3")),
        body=body,
        body_size=len(body),
        body_truncated=False,
        body_preview=body_preview(body),
        content_type="application/json",
        remote_addr="203.0.113.7",
        http_version="1.1",
        reply_status=200,
    )
