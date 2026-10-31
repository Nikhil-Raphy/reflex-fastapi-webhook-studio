"""Request and reply bodies for the management API."""

import base64
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from reflex_fastapi_webhook_studio.domain import (
    MAX_CONTENT_TYPE_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_REPLY_HEADERS,
    CapturedRequest,
    HttpMethod,
    ReplayResult,
    ReplyConfig,
)


def body_text(body: bytes) -> str | None:
    """Decode a body as UTF-8 text.

    Args:
        body: The body bytes.

    Returns:
        The text, or None when the body is not valid UTF-8.
    """
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


class BinCreate(BaseModel):
    """The body for creating a bin."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL_LENGTH)


class ReplyIn(BaseModel):
    """What a bin sends back. A missing field takes its default; a `null` body sends the default JSON body."""

    model_config = ConfigDict(extra="forbid")

    status: int = 200
    content_type: str | None = Field(default=None, max_length=MAX_CONTENT_TYPE_LENGTH)
    headers: list[tuple[str, str]] = Field(default_factory=list, max_length=MAX_REPLY_HEADERS)
    body: str | None = None
    delay_ms: int = 0

    def to_domain(self) -> ReplyConfig:
        """Turn the body into reply settings.

        Returns:
            The reply settings.
        """
        return ReplyConfig(
            status=self.status,
            content_type=self.content_type,
            headers=tuple(self.headers),
            body=self.body,
            delay_ms=self.delay_ms,
        )


class BinUpdate(BaseModel):
    """The body for changing a bin; leave a field out to keep it.

    `label: null` clears the label, and `reply: null` puts back the default reply.
    """

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL_LENGTH)
    reply: ReplyIn | None = None


class ReplayIn(BaseModel):
    """The body for replaying a request."""

    model_config = ConfigDict(extra="forbid")

    target_url: str = Field(min_length=1)
    use_original_query: bool = True


class ReplayOut(BaseModel):
    """What the target sent back. `body_text` is present only when the body is valid UTF-8."""

    status: int
    reason: str
    elapsed_ms: int
    headers: list[tuple[str, str]]
    body_base64: str
    body_text: str | None
    body_truncated: bool

    @classmethod
    def of(cls, result: ReplayResult) -> Self:
        """Build the reply body from a replay result.

        Args:
            result: The result.

        Returns:
            The reply body.
        """
        return cls(
            status=result.status,
            reason=result.reason,
            elapsed_ms=result.elapsed_ms,
            headers=list(result.headers),
            body_base64=base64.b64encode(result.body).decode("ascii"),
            body_text=body_text(result.body),
            body_truncated=result.body_truncated,
        )


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
            body_text=body_text(request.body),
            body_size=request.body_size,
            body_truncated=request.body_truncated,
            content_type=request.content_type,
            remote_addr=request.remote_addr,
            http_version=request.http_version,
            reply_status=request.reply_status,
        )


class HealthOut(BaseModel):
    """The health reply. `redis` is present only when the app uses Redis."""

    status: Literal["ok"]
    version: str
    database: Literal["ok"]
    redis: Literal["ok"] | None = None


class CaptureOut(BaseModel):
    """The default reply of a capture route."""

    ok: Literal[True]
    request_id: UUID
