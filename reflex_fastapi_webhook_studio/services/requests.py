"""Read and delete the requests a bin has caught."""

import logging
from typing import TYPE_CHECKING

from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus
from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import (
    EVERY_REQUEST,
    BinEvent,
    BinNotFoundError,
    EventType,
    RequestNotFoundError,
    is_bin_id,
)
from reflex_fastapi_webhook_studio.log_config import short_id

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from reflex_fastapi_webhook_studio.bus.base import EventBus
    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.domain import CapturedRequest, RequestFilter, RequestSummary

logger = logging.getLogger(__name__)


class RequestService:
    """Rules for reading and deleting captured requests."""

    def __init__(self, database: Database, *, bus: EventBus | None = None) -> None:
        """Set up the service.

        Args:
            database: The database.
            bus: Where to tell open inspectors about deletes; a bus with no subscribers when None.
        """
        self._database = database
        self._bus: EventBus = bus or MemoryBus()

    async def list(
        self, bin_id: str, *, limit: int, where: RequestFilter = EVERY_REQUEST, before: UUID | None = None
    ) -> list[RequestSummary]:
        """List a bin's requests that match a filter, newest first.

        Args:
            bin_id: The bin id.
            limit: The most requests to return.
            where: Which requests to list.
            before: Only requests older than the one with this id, to read the next page.

        Returns:
            Short forms of the requests.
        """
        async with self._database.sessions() as session:
            await _known_bin(session, bin_id)
            return await repository.list_requests(session, bin_id, limit=limit, where=where, before=before)

    async def count(self, bin_id: str, where: RequestFilter = EVERY_REQUEST) -> int:
        """Count a bin's requests that match a filter.

        Args:
            bin_id: The bin id.
            where: Which requests to count.

        Returns:
            The number of requests.
        """
        async with self._database.sessions() as session:
            await _known_bin(session, bin_id)
            return await repository.count_requests(session, bin_id, where)

    async def get(self, bin_id: str, request_id: UUID) -> CapturedRequest:
        """Read one request of a bin.

        Args:
            bin_id: The bin id.
            request_id: The request id.

        Returns:
            The request.

        Raises:
            BinNotFoundError: If the bin id is malformed.
            RequestNotFoundError: If the bin holds no request with that id.
        """
        if not is_bin_id(bin_id):
            raise BinNotFoundError
        async with self._database.sessions() as session:
            request = await repository.get_request(session, bin_id, request_id)
        if request is None:
            raise RequestNotFoundError
        return request

    async def delete(self, bin_id: str, request_id: UUID) -> None:
        """Delete one request of a bin, and tell its open inspectors.

        Args:
            bin_id: The bin id.
            request_id: The request id.

        Raises:
            BinNotFoundError: If the bin id is malformed.
            RequestNotFoundError: If the bin holds no request with that id.
        """
        if not is_bin_id(bin_id):
            raise BinNotFoundError
        async with self._database.sessions.begin() as session:
            deleted = await repository.delete_request(session, bin_id, request_id)
        if not deleted:
            raise RequestNotFoundError
        await self._bus.publish(BinEvent(type=EventType.REQUEST_DELETED, bin_id=bin_id, request_id=request_id))

    async def clear(self, bin_id: str) -> None:
        """Delete every request of a bin, and tell its open inspectors.

        Args:
            bin_id: The bin id.
        """
        async with self._database.sessions.begin() as session:
            await _known_bin(session, bin_id)
            await repository.clear_requests(session, bin_id)
        logger.info("Cleared bin %s", short_id(bin_id))
        await self._bus.publish(BinEvent(type=EventType.BIN_CLEARED, bin_id=bin_id))


async def _known_bin(session: AsyncSession, bin_id: str) -> None:
    """Check that a bin exists.

    Args:
        session: An open session.
        bin_id: The bin id.

    Raises:
        BinNotFoundError: If the id is malformed or no bin has it.
    """
    if not is_bin_id(bin_id) or await repository.get_bin(session, bin_id) is None:
        raise BinNotFoundError
