"""Create, read and rename bins."""

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus
from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import (
    MAX_CONTENT_TYPE_LENGTH,
    MAX_REPLY_BODY_BYTES,
    MAX_REPLY_HEADERS,
    NO_BODY_STATUSES,
    Bin,
    BinEvent,
    BinLimitError,
    BinListing,
    BinNotFoundError,
    BinSummary,
    Clock,
    EventType,
    InvalidReplyError,
    ListingOffError,
    ReplyConfig,
    is_bin_id,
    new_bin_id,
    utc_now,
)
from reflex_fastapi_webhook_studio.log_config import short_id
from reflex_fastapi_webhook_studio.security.header_rules import is_field_value, reply_header_problem

if TYPE_CHECKING:
    from collections.abc import Iterable

    from reflex_fastapi_webhook_studio.bus.base import EventBus
    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.settings import Settings

MIN_REPLY_STATUS = 200
MAX_REPLY_STATUS = 599

logger = logging.getLogger(__name__)


def reply_problem(reply: ReplyConfig, *, max_delay_ms: int) -> str | None:
    """Check reply settings against the rules for a bin's reply.

    Args:
        reply: The reply settings.
        max_delay_ms: The longest delay allowed.

    Returns:
        What is wrong, or None if the settings are allowed.
    """
    if not MIN_REPLY_STATUS <= reply.status <= MAX_REPLY_STATUS:
        return f"The status must be from {MIN_REPLY_STATUS} to {MAX_REPLY_STATUS}."
    if not 0 <= reply.delay_ms <= max_delay_ms:
        return f"The delay must be from 0 to {max_delay_ms} ms."
    return _body_problem(reply) or _headers_problem(reply)


def _body_problem(reply: ReplyConfig) -> str | None:
    if reply.body is not None and reply.status in NO_BODY_STATUSES:
        return f"A {reply.status} reply has no body."
    if reply.body is not None and len(reply.body.encode()) > MAX_REPLY_BODY_BYTES:
        return f"The body may hold at most {MAX_REPLY_BODY_BYTES // 1024} KiB."
    content_type = reply.content_type
    if content_type is not None and (
        not content_type or len(content_type) > MAX_CONTENT_TYPE_LENGTH or not is_field_value(content_type)
    ):
        return "The content type is empty, too long, or holds a control character."
    return None


def _headers_problem(reply: ReplyConfig) -> str | None:
    if len(reply.headers) > MAX_REPLY_HEADERS:
        return f"A reply may set at most {MAX_REPLY_HEADERS} headers."
    problems = (reply_header_problem(name, value) for name, value in reply.headers)
    return next((problem for problem in problems if problem is not None), None)


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

    async def set_reply(self, bin_id: str, reply: ReplyConfig) -> Bin:
        """Change what a bin sends back to senders, and tell its open inspectors.

        Args:
            bin_id: The bin id.
            reply: The new reply settings.

        Returns:
            The changed bin.

        Raises:
            InvalidReplyError: If the settings break a rule.
            BinNotFoundError: If the id is malformed or no bin has it.
        """
        problem = reply_problem(reply, max_delay_ms=self._settings.max_delay_ms)
        if problem is not None:
            raise InvalidReplyError(problem)
        if is_bin_id(bin_id):
            async with self._database.sessions.begin() as session:
                bin_ = await repository.set_reply(session, bin_id, reply)
            if bin_ is not None:
                await self._bus.publish(BinEvent(type=EventType.BIN_UPDATED, bin_id=bin_id, label=bin_.label))
                return bin_
        raise BinNotFoundError

    async def delete(self, bin_id: str) -> None:
        """Delete a bin with its requests, and tell its open inspectors.

        Args:
            bin_id: The bin id.

        Raises:
            BinNotFoundError: If the id is malformed or no bin has it.
        """
        if not is_bin_id(bin_id):
            raise BinNotFoundError
        async with self._database.sessions.begin() as session:
            deleted = await repository.delete_bin(session, bin_id)
        if not deleted:
            raise BinNotFoundError
        logger.info("Deleted bin %s", short_id(bin_id))
        await self._bus.publish(BinEvent(type=EventType.BIN_DELETED, bin_id=bin_id))
