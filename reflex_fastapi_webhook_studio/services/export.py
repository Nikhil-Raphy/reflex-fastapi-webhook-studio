"""Write a whole bin, with every request, as one JSON document."""

import base64
import json
from contextlib import suppress
from typing import TYPE_CHECKING

from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import BinNotFoundError, Clock, is_bin_id, utc_now

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime
    from uuid import UUID

    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.domain import Bin, CapturedRequest

EXPORT_FORMAT = "webhook-studio-export"
EXPORT_VERSION = 1
BATCH_SIZE = 20
"""Requests read per query; bodies may be up to the size cap each, so the batch stays small."""


class ExportService:
    """Streams a bin as JSON, so a full bin never sits in memory at once."""

    def __init__(self, database: Database, *, clock: Clock = utc_now) -> None:
        """Set up the service.

        Args:
            database: The database.
            clock: Gives the current time.
        """
        self._database = database
        self._clock = clock

    async def export(self, bin_id: str) -> AsyncIterator[bytes]:
        """Check the bin, then give the export as chunks of JSON, with requests oldest first.

        Args:
            bin_id: The bin id.

        Returns:
            The chunks; together they form one JSON document.

        Raises:
            BinNotFoundError: If the id is malformed or no bin has it.
        """
        if not is_bin_id(bin_id):
            raise BinNotFoundError
        async with self._database.sessions() as session:
            bin_ = await repository.get_bin(session, bin_id)
        if bin_ is None:
            raise BinNotFoundError
        return self._chunks(bin_)

    async def _chunks(self, bin_: Bin) -> AsyncIterator[bytes]:
        head = json.dumps(
            {
                "format": EXPORT_FORMAT,
                "version": EXPORT_VERSION,
                "exported_at": _time(self._clock()),
                "bin": _bin(bin_),
            },
            ensure_ascii=False,
        )
        yield f'{head[:-1]}, "requests": ['.encode()
        after: UUID | None = None
        first = True
        while True:
            async with self._database.sessions() as session:
                batch = await repository.requests_after(session, bin_.id, after=after, limit=BATCH_SIZE)
            for request in batch:
                yield (b"" if first else b", ") + json.dumps(_request(request), ensure_ascii=False).encode()
                first = False
            if len(batch) < BATCH_SIZE:
                break
            after = batch[-1].id
        yield b"]}"


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _bin(bin_: Bin) -> dict[str, object]:
    return {
        "id": bin_.id,
        "label": bin_.label,
        "created_at": _time(bin_.created_at),
        "last_activity_at": _time(bin_.last_activity_at),
        "expires_at": _time(bin_.expires_at),
        "reply": {
            "status": bin_.reply.status,
            "content_type": bin_.reply.content_type,
            "headers": [list(pair) for pair in bin_.reply.headers],
            "body": bin_.reply.body,
            "delay_ms": bin_.reply.delay_ms,
        },
    }


def _request(request: CapturedRequest) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": str(request.id),
        "received_at": _time(request.received_at),
        "method": request.method.value,
        "path": request.path,
        "query_string": request.query_string,
        "query_params": [list(pair) for pair in request.query_params],
        "headers": [list(pair) for pair in request.headers],
        "body_base64": base64.b64encode(request.body).decode("ascii"),
        "body_size": request.body_size,
        "body_truncated": request.body_truncated,
        "content_type": request.content_type,
        "remote_addr": request.remote_addr,
        "http_version": request.http_version,
        "reply_status": request.reply_status,
    }
    with suppress(UnicodeDecodeError):
        entry["body_text"] = request.body.decode("utf-8")
    return entry
