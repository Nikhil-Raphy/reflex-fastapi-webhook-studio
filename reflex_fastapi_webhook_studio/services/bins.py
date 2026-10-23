"""Create, read and rename bins."""

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus
from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import (
    Bin,
    BinEvent,
    BinLimitError,
    BinListing,
    BinNotFoundError,
    BinSummary,
    Clock,
    EventType,
    ListingOffError,
    is_bin_id,
    new_bin_id,
    utc_now,
)
from reflex_fastapi_webhook_studio.log_config import short_id

if TYPE_CHECKING:
    from collections.abc import Iterable

    from reflex_fastapi_webhook_studio.bus.base import EventBus
    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.settings import Settings

logger = logging.getLogger(__name__)


class BinService:
    """Rules for bins."""

    def __init__(
        self, database: Database, settings: Settings, *, bus: EventBus | None = None, clock: Clock = utc_now
    ) -> None:
        """Set up the service.

        Args:
            database: The database.
            settings: The app settings.
            bus: Where to tell open inspectors about bin changes; a bus with no subscribers when None.
            clock: Gives the current time.
        """
        self._database = database
        self._settings = settings
        self._bus: EventBus = bus or MemoryBus()
        self._clock = clock

    async def create(self, label: str | None) -> Bin:
        """Create a bin with a new random id.

        Args:
            label: An optional name.

        Returns:
            The new bin.

        Raises:
            BinLimitError: If the app already holds the most bins it may.
        """
        now = self._clock()
        bin_ = Bin(
            id=new_bin_id(),
            label=label,
            created_at=now,
            last_activity_at=now,
            expires_at=now + timedelta(days=self._settings.bin_ttl_days),
        )
        async with self._database.sessions.begin() as session:
            if await repository.count_bins(session) >= self._settings.max_bins:
                raise BinLimitError
            await repository.add_bin(session, bin_)
        logger.info("Created bin %s", short_id(bin_.id))
        return bin_

    async def get(self, bin_id: str) -> Bin:
        """Read a bin.

        Args:
            bin_id: The bin id.

        Returns:
            The bin.

        Raises:
            BinNotFoundError: If the id is malformed or no bin has it.
        """
        if is_bin_id(bin_id):
            async with self._database.sessions() as session:
                bin_ = await repository.get_bin(session, bin_id)
            if bin_ is not None:
                return bin_
        raise BinNotFoundError

    async def list_all(self) -> list[BinSummary]:
        """List every bin, the most recently active first.

        Returns:
            Short forms of the bins.

        Raises:
            ListingOffError: If the listing mode is `browser`.
        """
        if self._settings.bin_listing is not BinListing.ALL:
            raise ListingOffError
        async with self._database.sessions() as session:
            return await repository.list_bins(session)

    async def summaries(self, bin_ids: Iterable[str]) -> list[BinSummary]:
        """List the given bins that exist, the most recently active first.

        Args:
            bin_ids: Bin ids, such as the ones a browser remembers; malformed and unknown ids are skipped.

        Returns:
            Short forms of the bins.
        """
        wanted = {bin_id for bin_id in bin_ids if is_bin_id(bin_id)}
        if not wanted:
            return []
        async with self._database.sessions() as session:
            return await repository.list_bins(session, wanted)

    async def rename(self, bin_id: str, label: str | None) -> Bin:
        """Change the label of a bin, and tell its open inspectors.

        Args:
            bin_id: The bin id.
            label: The new label, or None to clear it.

        Returns:
            The renamed bin.

        Raises:
            BinNotFoundError: If the id is malformed or no bin has it.
        """
        if is_bin_id(bin_id):
            async with self._database.sessions.begin() as session:
                bin_ = await repository.set_label(session, bin_id, label)
            if bin_ is not None:
                await self._bus.publish(BinEvent(type=EventType.BIN_UPDATED, bin_id=bin_id, label=label))
                return bin_
        raise BinNotFoundError
