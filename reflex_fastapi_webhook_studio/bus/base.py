"""The contract every event bus keeps."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from reflex_fastapi_webhook_studio.domain import BinEvent


@runtime_checkable
class Subscription(Protocol):
    """The events of one bin, for one subscriber, in the order they were published."""

    async def next(self, wait_s: float) -> BinEvent | None:
        """Wait for the next event.

        Args:
            wait_s: The most seconds to wait.

        Returns:
            The event, or None if none came in time.
        """
        ...


@runtime_checkable
class EventBus(Protocol):
    """Carries bin events from the worker that made them to every subscriber of that bin."""

    async def publish(self, event: BinEvent) -> None:
        """Send an event to every subscriber of its bin. It never raises; a lost event is logged.

        Args:
            event: The event.
        """
        ...

    def subscribe(self, bin_id: str) -> AbstractAsyncContextManager[Subscription]:
        """Follow one bin's events until the context ends.

        Args:
            bin_id: The bin id.

        Returns:
            A context that yields the subscription.
        """
        ...
