"""Store a request that reached a capture route."""

import logging
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl
from uuid import uuid7

from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import (
    BinNotFoundError,
    CapturedRequest,
    Clock,
    body_preview,
    is_bin_id,
    storable_text,
    utc_now,
)
from reflex_fastapi_webhook_studio.log_config import short_id

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.domain import IncomingRequest
    from reflex_fastapi_webhook_studio.settings import Settings

logger = logging.getLogger(__name__)


class CaptureService:
    """Rules for storing captured requests."""

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

    async def capture(self, bin_id: str, incoming: IncomingRequest, *, reply_status: int) -> CapturedRequest:
        """Store a request, drop the bin's oldest beyond the cap, and push the bin's expiry out, in one transaction.

        Args:
            bin_id: The bin id from the URL.
            incoming: The request as it arrived.
            reply_status: The status code the route will send back.

        Returns:
            The stored request.

        Raises:
            BinNotFoundError: If the id is malformed or no bin has it.
        """
        if not is_bin_id(bin_id):
            raise BinNotFoundError
        now = self._clock()
        request = CapturedRequest(
            id=uuid7(),
            bin_id=bin_id,
            received_at=now,
            method=incoming.method,
            path=storable_text(incoming.path),
            query_string=storable_text(incoming.query_string),
            query_params=tuple(
                (storable_text(name), storable_text(value))
                for name, value in parse_qsl(incoming.query_string, keep_blank_values=True)
            ),
            headers=tuple((storable_text(name), storable_text(value)) for name, value in incoming.headers),
            body=incoming.body,
            body_size=incoming.body_size,
            body_truncated=incoming.body_truncated,
            body_preview=body_preview(incoming.body),
            content_type=None if incoming.content_type is None else storable_text(incoming.content_type),
            remote_addr=incoming.remote_addr,
            http_version=incoming.http_version,
            reply_status=reply_status,
        )
        async with self._database.sessions.begin() as session:
            if await repository.get_bin(session, bin_id) is None:
                raise BinNotFoundError
            await repository.add_request(session, request)
            await repository.trim_requests(session, bin_id, keep=self._settings.max_requests_per_bin)
            await repository.touch_bin(
                session, bin_id, at=now, expires_at=now + timedelta(days=self._settings.bin_ttl_days)
            )
        logger.info(
            "Captured %s request in bin %s, %d body bytes, reply %d",
            request.method,
            short_id(bin_id),
            request.body_size,
            reply_status,
        )
        return request
