"""Create, read and rename bins."""

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import (
    Bin,
    BinLimitError,
    BinNotFoundError,
    Clock,
    is_bin_id,
    new_bin_id,
    utc_now,
)
from reflex_fastapi_webhook_studio.log_config import short_id

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.settings import Settings

logger = logging.getLogger(__name__)


class BinService:
    """Rules for bins."""

    def __init__(self, database: Database, settings: Settings, clock: Clock = utc_now) -> None:
        """Set up the service.

        Args:
            database: The database.
            settings: The app settings.
            clock: Gives the current time.
        """
        self._database = database
        self._settings = settings
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

    async def rename(self, bin_id: str, label: str | None) -> Bin:
        """Change the label of a bin.

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
                return bin_
        raise BinNotFoundError
