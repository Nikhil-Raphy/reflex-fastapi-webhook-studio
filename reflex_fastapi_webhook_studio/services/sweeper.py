"""Delete expired bins on a timer, in every worker."""

import asyncio
import logging
import random
from collections.abc import AsyncIterator  # noqa: TC003  # Reflex reads lifespan task signatures at run time.
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus
from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import BinEvent, Clock, EventType, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable

    from reflex_fastapi_webhook_studio.bus.base import EventBus
    from reflex_fastapi_webhook_studio.db.engine import Database

FIRST_SWEEP_MOST_S = 30.0
JITTER = 0.1
"""Each wait varies by up to this share, so workers that started together do not sweep together."""

logger = logging.getLogger(__name__)


def jittered(seconds: float) -> float:
    """Vary a wait at random by up to 10% either way.

    Args:
        seconds: The planned wait.

    Returns:
        The wait to use.
    """
    # Spreads load only; nothing here needs a secure random source.
    return seconds * random.uniform(1 - JITTER, 1 + JITTER)  # noqa: S311


class Sweeper:
    """Deletes bins past their expiry, with their requests, and tells their open inspectors."""

    def __init__(
        self,
        database: Database,
        interval_s: float,
        *,
        bus: EventBus | None = None,
        clock: Clock = utc_now,
        vary: Callable[[float], float] = jittered,
    ) -> None:
        """Set up the sweeper.

        Args:
            database: The database.
            interval_s: Seconds between sweeps.
            bus: Where to tell open inspectors about deleted bins; a bus with no subscribers when None.
            clock: Gives the current time.
            vary: Turns a planned wait into the wait to use.
        """
        self._database = database
        self._interval_s = interval_s
        self._bus: EventBus = bus or MemoryBus()
        self._clock = clock
        self._vary = vary

    async def sweep(self) -> list[str]:
        """Delete every expired bin now. Running it twice, or in two workers at once, does no harm.

        Returns:
            The ids of the deleted bins.
        """
        async with self._database.sessions.begin() as session:
            deleted = await repository.delete_expired_bins(session, self._clock())
        if deleted:
            logger.info("Deleted %d expired bins", len(deleted))
        for bin_id in deleted:
            await self._bus.publish(BinEvent(type=EventType.BIN_DELETED, bin_id=bin_id))
        return deleted

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Sweep soon after start, then once per interval, for as long as the server runs.

        Yields:
            Nothing; the sweeps run until the context ends.
        """
        task = asyncio.create_task(self._sweep_forever())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _sweep_forever(self) -> None:
        await asyncio.sleep(self._vary(min(FIRST_SWEEP_MOST_S, self._interval_s)))
        while True:
            try:
                await self.sweep()
            except (SQLAlchemyError, OSError) as error:
                logger.warning("Could not delete expired bins: %s", type(error).__name__)
            await asyncio.sleep(self._vary(self._interval_s))
