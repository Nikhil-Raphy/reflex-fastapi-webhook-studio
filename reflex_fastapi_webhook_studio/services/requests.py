"""Read the requests a bin has caught."""

from typing import TYPE_CHECKING

from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import BinNotFoundError, RequestNotFoundError, is_bin_id

if TYPE_CHECKING:
    from uuid import UUID

    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.domain import CapturedRequest, RequestSummary


class RequestService:
    """Rules for reading captured requests."""

    def __init__(self, database: Database) -> None:
        """Set up the service.

        Args:
            database: The database.
        """
        self._database = database

    async def list(self, bin_id: str, *, limit: int) -> list[RequestSummary]:
        """List the newest requests of a bin, newest first.

        Args:
            bin_id: The bin id.
            limit: The most requests to return.

        Returns:
            Short forms of the requests.

        Raises:
            BinNotFoundError: If the id is malformed or no bin has it.
        """
        if not is_bin_id(bin_id):
            raise BinNotFoundError
        async with self._database.sessions() as session:
            if await repository.get_bin(session, bin_id) is None:
                raise BinNotFoundError
            return await repository.list_requests(session, bin_id, limit=limit)

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
