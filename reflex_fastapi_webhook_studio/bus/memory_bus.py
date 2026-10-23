"""An event bus inside one process, for one worker."""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from reflex_fastapi_webhook_studio.domain import BinEvent, EventType

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

QUEUE_SIZE = 256


class MemorySubscription:
    """One subscriber's queue of events for one bin."""

    def __init__(self, bin_id: str, size: int) -> None:
        """Make an empty queue.

        Args:
            bin_id: The bin id.
            size: The most events the queue holds.
        """
        self.bin_id = bin_id
        self._queue: asyncio.Queue[BinEvent] = asyncio.Queue(maxsize=size)

    def offer(self, event: BinEvent) -> None:
        """Queue an event without waiting.

        A full queue means the subscriber fell behind. It is emptied and given one `resync`, since a reload from the
        database covers every event it held.

        Args:
            event: The event.
        """
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queue.put_nowait(BinEvent(type=EventType.RESYNC, bin_id=self.bin_id))

    async def next(self, wait_s: float) -> BinEvent | None:
        """Wait for the next event.

        Args:
            wait_s: The most seconds to wait.

        Returns:
            The event, or None if none came in time.
        """
        try:
            async with asyncio.timeout(wait_s):
                return await self._queue.get()
        except TimeoutError:
            return None


class MemoryBus:
    """Delivers events to subscribers in the same process."""

    def __init__(self, queue_size: int = QUEUE_SIZE) -> None:
        """Start with no subscribers.

        Args:
            queue_size: The most events each subscriber's queue holds.
        """
        self._queue_size = queue_size
        self._subscribers: defaultdict[str, set[MemorySubscription]] = defaultdict(set)

    async def publish(self, event: BinEvent) -> None:
        """Send an event to every subscriber of its bin.

        Args:
            event: The event.
        """
        self.deliver(event)

    def deliver(self, event: BinEvent) -> None:
        """Send an event to every subscriber of its bin, without waiting.

        Args:
            event: The event.
        """
        for subscription in tuple(self._subscribers.get(event.bin_id, ())):
            subscription.offer(event)

    def resync_all(self) -> None:
        """Tell every subscriber to reload, after events may have been lost."""
        for bin_id, subscriptions in tuple(self._subscribers.items()):
            for subscription in tuple(subscriptions):
                subscription.offer(BinEvent(type=EventType.RESYNC, bin_id=bin_id))

    @asynccontextmanager
    async def subscribe(self, bin_id: str) -> AsyncIterator[MemorySubscription]:
        """Follow one bin's events until the context ends.

        Args:
            bin_id: The bin id.

        Yields:
            The subscription.
        """
        subscription = MemorySubscription(bin_id, self._queue_size)
        self._subscribers[bin_id].add(subscription)
        try:
            yield subscription
        finally:
            subscriptions = self._subscribers[bin_id]
            subscriptions.discard(subscription)
            if not subscriptions:
                del self._subscribers[bin_id]
