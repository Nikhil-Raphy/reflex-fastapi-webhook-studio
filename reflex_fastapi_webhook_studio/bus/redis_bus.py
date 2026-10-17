"""An event bus over Redis pub/sub, so every worker hears every event."""

import asyncio
import logging
from collections.abc import AsyncIterator  # noqa: TC003  # Reflex reads lifespan task signatures at run time.
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError
from redis.exceptions import RedisError

from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus, MemorySubscription
from reflex_fastapi_webhook_studio.domain import BinEvent
from reflex_fastapi_webhook_studio.log_config import short_id

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from redis.asyncio import Redis

CHANNEL_PREFIX = "webhook-studio:bin:"
RETRY_FIRST_S = 1.0
RETRY_MOST_S = 30.0

logger = logging.getLogger(__name__)
_events = TypeAdapter(BinEvent)


class RedisBus:
    """Publishes to one Redis channel per bin; one pattern listener per worker feeds a local `MemoryBus`."""

    def __init__(self, redis: Redis, local: MemoryBus | None = None) -> None:
        """Set up the bus.

        Args:
            redis: The async Redis client.
            local: The bus that hands events to this worker's subscribers.
        """
        self._redis = redis
        self._local = local or MemoryBus()
        self.ready = asyncio.Event()
        """Set while this worker's listener is subscribed."""

    async def publish(self, event: BinEvent) -> None:
        """Publish an event on its bin's channel. A Redis failure is logged, not raised.

        Args:
            event: The event.
        """
        try:
            await self._redis.publish(f"{CHANNEL_PREFIX}{event.bin_id}", _events.dump_json(event))
        except (RedisError, OSError) as error:
            logger.warning("Could not publish %s for bin %s: %s", event.type, short_id(event.bin_id), error)

    def subscribe(self, bin_id: str) -> AbstractAsyncContextManager[MemorySubscription]:
        """Follow one bin's events until the context ends.

        Args:
            bin_id: The bin id.

        Returns:
            A context that yields the subscription.
        """
        return self._local.subscribe(bin_id)

    @asynccontextmanager
    async def listen(self) -> AsyncIterator[None]:
        """Run this worker's listener for as long as the server runs.

        Yields:
            Nothing; the listener runs until the context ends.
        """
        task = asyncio.create_task(self._listen_forever())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _listen_forever(self) -> None:
        wait_s = RETRY_FIRST_S
        lost = False
        while True:
            try:
                async with self._redis.pubsub() as pubsub:
                    await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
                    if lost:
                        # Redis keeps no messages, so subscribers reload what they may have missed.
                        self._local.resync_all()
                    wait_s, lost = RETRY_FIRST_S, False
                    self.ready.set()
                    async for message in pubsub.listen():
                        if message["type"] == "pmessage":
                            self.deliver(message["data"])
            except (RedisError, OSError) as error:
                self.ready.clear()
                logger.warning("Lost the Redis event listener; retrying in %s s: %s", wait_s, error)
                lost = True
                await asyncio.sleep(wait_s)
                wait_s = min(wait_s * 2, RETRY_MOST_S)

    def deliver(self, raw: bytes | str) -> None:
        """Hand one published event to this worker's subscribers; a message that is not an event is logged.

        Args:
            raw: The message body, as JSON.
        """
        try:
            event = _events.validate_json(raw)
        except ValidationError:
            logger.warning("Ignored a Redis message that is not a bin event")
            return
        self._local.deliver(event)
