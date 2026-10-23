"""Tests for the Redis event bus; they run when WEBHOOK_STUDIO_TEST_REDIS_URL names a Redis server."""

# Fixtures take other fixtures as arguments of the same name.
# pylint: disable=redefined-outer-name

import asyncio
import os
from typing import TYPE_CHECKING

import pytest
from redis.asyncio import Redis

from reflex_fastapi_webhook_studio.bus.redis_bus import CHANNEL_PREFIX, RedisBus
from reflex_fastapi_webhook_studio.domain import BinEvent, EventType

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

TEST_REDIS_URL = "WEBHOOK_STUDIO_TEST_REDIS_URL"
BIN = "AbCdEfGhIjKlMnOpQrStUv"
EVENT = BinEvent(type=EventType.BIN_UPDATED, bin_id=BIN, label="new")
RESYNC = BinEvent(type=EventType.RESYNC, bin_id=BIN)


@pytest.fixture
async def redis_url() -> str:
    """Give the test Redis URL, or skip.

    Returns:
        The URL.
    """
    url = os.environ.get(TEST_REDIS_URL, "")
    if not url:
        pytest.skip(f"{TEST_REDIS_URL} is not set")
    return url


@pytest.fixture
async def clients(redis_url: str) -> AsyncIterator[list[Redis]]:
    """Open three Redis clients: two workers and one publisher.

    Args:
        redis_url: The test Redis URL.

    Yields:
        The clients.
    """
    opened = [Redis.from_url(redis_url) for _ in range(3)]
    yield opened
    for client in opened:
        await client.aclose()


async def wait_for_listeners(*buses: RedisBus) -> None:
    """Wait until each bus's listener has subscribed.

    Args:
        *buses: The buses.
    """
    async with asyncio.timeout(5):
        for bus in buses:
            await bus.ready.wait()


@pytest.mark.redis
@pytest.mark.anyio
async def test_given_two_workers_when_event_is_published_then_both_get_it(clients: list[Redis]) -> None:
    """Given Redis and subscribers on two workers, when an event is published, then both get it."""
    # Given
    first, second, publisher = RedisBus(clients[0]), RedisBus(clients[1]), RedisBus(clients[2])
    async with first.listen(), second.listen(), first.subscribe(BIN) as one, second.subscribe(BIN) as two:
        await wait_for_listeners(first, second)
        # When
        await publisher.publish(EVENT)
        got = [await one.next(2), await two.next(2)]
    # Then
    assert got == [EVENT, EVENT]


@pytest.mark.redis
@pytest.mark.anyio
async def test_given_listener_when_junk_arrives_then_it_is_skipped(clients: list[Redis]) -> None:
    """Given a worker listening, when a message that is not an event arrives, then it is skipped and the next comes."""
    # Given
    worker, publisher = RedisBus(clients[0]), RedisBus(clients[1])
    async with worker.listen(), worker.subscribe(BIN) as events:
        await wait_for_listeners(worker)
        # When
        await clients[1].publish(f"{CHANNEL_PREFIX}{BIN}", b"not json")
        await publisher.publish(EVENT)
        got = await events.next(2)
    # Then
    assert got == EVENT


@pytest.mark.redis
@pytest.mark.anyio
async def test_given_listener_when_its_connection_drops_then_subscribers_get_resync(clients: list[Redis]) -> None:
    """Given a worker listening, when Redis drops its listener, then it reconnects and its subscribers resync."""
    # Given
    worker = RedisBus(clients[0])
    async with worker.listen(), worker.subscribe(BIN) as events:
        await wait_for_listeners(worker)
        # When
        await clients[1].client_kill_filter(_type="pubsub")
        got = await events.next(5)
    # Then
    assert got == RESYNC


@pytest.mark.anyio
async def test_given_redis_down_when_event_is_published_then_no_error_reaches_the_caller() -> None:
    """Given no Redis on the port, when an event is published, then the bus logs and the caller carries on."""
    # Given
    client = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=1)
    bus = RedisBus(client)
    # When
    await bus.publish(EVENT)
    # Then
    await client.aclose()
