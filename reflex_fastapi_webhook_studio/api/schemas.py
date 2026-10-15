"""Request and reply bodies for the management API."""

import base64
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from reflex_fastapi_webhook_studio.domain import MAX_LABEL_LENGTH, CapturedRequest, HttpMethod


class BinCreate(BaseModel):
    """The body for creating a bin."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL_LENGTH)


class BinUpdate(BaseModel):
    """The body for changing a bin; `label: null` clears the label."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(min_length=1, max_length=MAX_LABEL_LENGTH)


class RequestDetailOut(BaseModel):
    """A captured request with every detail. `body_text` is present only when the body is valid UTF-8."""

    id: UUID
    bin_id: str
    received_at: datetime
    method: HttpMethod
    path: str
    query_string: str
    query_params: list[tuple[str, str]]
    headers: list[tuple[str, str]]
    body_base64: str
    body_text: str | None
    body_size: int
    body_truncated: bool
    content_type: str | None
    remote_addr: str | None
    http_version: str
    reply_status: int

    @classmethod
    def of(cls, request: CapturedRequest) -> Self:
        """Build the reply body from a captured request.

        Args:
            request: The request.

        Returns:
            The reply body.
        """
        try:
            text: str | None = request.body.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        return cls(
            id=request.id,
            bin_id=request.bin_id,
            received_at=request.received_at,
            method=request.method,
            path=request.path,
            query_string=request.query_string,
            query_params=list(request.query_params),
            headers=list(request.headers),
            body_base64=base64.b64encode(request.body).decode("ascii"),
            body_text=text,
            body_size=request.body_size,
            body_truncated=request.body_truncated,
            content_type=request.content_type,
            remote_addr=request.remote_addr,
            http_version=request.http_version,
            reply_status=request.reply_status,
        )


class HealthOut(BaseModel):
    """The health reply."""

    status: Literal["ok"]
    version: str
    database: Literal["ok"]


class CaptureOut(BaseModel):
    """The default reply of a capture route."""

    ok: Literal[True]
    request_id: UUID
