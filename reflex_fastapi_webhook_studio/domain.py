"""Value types and errors shared by every layer."""

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Callable

BIN_ID_LENGTH = 22
MAX_LABEL_LENGTH = 80
MAX_SEARCH_LENGTH = 200
PREVIEW_BYTES = 4096
MAX_REPLY_BODY_BYTES = 65_536
MAX_REPLY_HEADERS = 32
MAX_CONTENT_TYPE_LENGTH = 255
NO_BODY_STATUSES = frozenset({204, 205, 304})
"""Statuses whose replies never carry a body."""
_BIN_ID_PATTERN = re.compile(rf"[A-Za-z0-9_-]{{{BIN_ID_LENGTH}}}")

type NameValuePairs = tuple[tuple[str, str], ...]
"""Header or query pairs, in the order they arrived, repeats kept."""

type Clock = Callable[[], datetime]
"""Returns the current time; tests pass a fixed one."""


def utc_now() -> datetime:
    """Read the current time.

    Returns:
        The current time in UTC.
    """
    return datetime.now(UTC)


class HttpMethod(StrEnum):
    """HTTP methods the capture routes accept."""

    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"


class BinNotFoundError(LookupError):
    """No bin has the given id."""


class BinListing(StrEnum):
    """Which bins the home page lists."""

    BROWSER = "browser"
    """Only the bins this browser made."""
    ALL = "all"
    """Every bin in the database."""


class ReplayMode(StrEnum):
    """Which addresses a replay may reach."""

    RESTRICTED = "restricted"
    """Only public internet addresses."""
    LOCAL = "local"
    """Any address, including this machine and private networks."""


class ListingOffError(LookupError):
    """Listing every bin is off, because the listing mode is `browser`."""


class RequestNotFoundError(LookupError):
    """The bin holds no request with the given id."""


class BinLimitError(Exception):
    """The app already holds the most bins it may."""


class InvalidReplyError(ValueError):
    """Reply settings break a rule; the message says which."""


class ReplayTargetError(ValueError):
    """The replay target is not an http or https URL with a host."""


class ReplayBlockedError(PermissionError):
    """The replay target resolves to an address that the replay mode does not allow."""


class ReplayFailedError(Exception):
    """The replay could not reach the target or get a full reply; the message says why."""


@dataclass(slots=True, frozen=True, kw_only=True)
class RequestFilter:
    """Which of a bin's requests to list.

    Attributes:
        method: Only requests with this method; every method when None.
        text: Only requests whose method, path, query string, headers or body preview hold this text, in any case.
    """

    method: HttpMethod | None = None
    text: str = ""

    @property
    def active(self) -> bool:
        """Whether the filter leaves out any request.

        Returns:
            True when a method or text is set.
        """
        return self.method is not None or bool(self.text)


EVERY_REQUEST = RequestFilter()


def new_bin_id() -> str:
    """Make a random bin id.

    Returns:
        A 22-character URL-safe id holding 128 random bits.
    """
    return secrets.token_urlsafe(16)


def is_bin_id(value: str) -> bool:
    """Check that a value has the form of a bin id.

    Args:
        value: The value to check.

    Returns:
        Whether the value is 22 URL-safe characters.
    """
    return _BIN_ID_PATTERN.fullmatch(value) is not None


def storable_text(value: str) -> str:
    """Replace NUL characters, which PostgreSQL text and JSON columns refuse.

    Args:
        value: Text taken from a request.

    Returns:
        The text with each NUL replaced by U+FFFD.
    """
    return value.replace("\x00", "\ufffd")


def body_preview(body: bytes) -> str:
    """Turn the first 4 KiB of a body into text for lists and search.

    Args:
        body: The body bytes.

    Returns:
        The text, with bytes that are not UTF-8 and NUL characters replaced by U+FFFD.
    """
    return storable_text(body[:PREVIEW_BYTES].decode("utf-8", errors="replace"))


@dataclass(slots=True, frozen=True, kw_only=True)
class ReplyConfig:
    """What a bin sends back to senders.

    Attributes:
        status: The status code.
        content_type: The Content-Type of the body, if any.
        headers: More reply headers, as name-value pairs.
        body: The body text; None sends the default JSON body with the request id.
        delay_ms: How long to wait before replying, in milliseconds.
    """

    status: int = 200
    content_type: str | None = None
    headers: NameValuePairs = ()
    body: str | None = None
    delay_ms: int = 0


DEFAULT_REPLY = ReplyConfig()


@dataclass(slots=True, frozen=True, kw_only=True)
class Bin:
    """A bin that collects requests.

    Attributes:
        id: The secret 22-character id.
        label: An optional name chosen by the user.
        created_at: When the bin was made.
        last_activity_at: When the bin last caught a request, or when it was made.
        expires_at: When the bin may be deleted.
        reply: What the bin sends back to senders.
    """

    id: str
    label: str | None
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    reply: ReplyConfig = DEFAULT_REPLY


@dataclass(slots=True, frozen=True, kw_only=True)
class BinSummary:
    """The short form of a bin, for lists.

    Attributes:
        id: The secret 22-character id.
        label: An optional name chosen by the user.
        created_at: When the bin was made.
        last_activity_at: When the bin last caught a request, or when it was made.
        expires_at: When the bin may be deleted.
        request_count: How many requests the bin holds.
    """

    id: str
    label: str | None
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    request_count: int


@dataclass(slots=True, frozen=True, kw_only=True)
class IncomingRequest:
    """A request as it reached a capture route, before it is stored.

    Attributes:
        method: The HTTP method.
        path: The sub-path after the bin id, starting with "/".
        query_string: The raw query string.
        headers: The headers as name-value pairs.
        body: The body bytes; empty when the body was over the cap.
        body_size: The number of body bytes read.
        body_truncated: Whether reading stopped at the cap.
        content_type: The Content-Type header, if any.
        remote_addr: The client address, if known.
        http_version: The HTTP version, such as "1.1".
    """

    method: HttpMethod
    path: str
    query_string: str
    headers: NameValuePairs
    body: bytes
    body_size: int
    body_truncated: bool
    content_type: str | None
    remote_addr: str | None
    http_version: str


@dataclass(slots=True, frozen=True, kw_only=True)
class RequestSummary:
    """The short form of a stored request, for lists.

    Attributes:
        id: The UUIDv7 id, which sorts by time.
        received_at: When the request arrived.
        method: The HTTP method.
        path: The sub-path after the bin id.
        query_string: The raw query string.
        body_size: The number of body bytes read.
        body_truncated: Whether the body was over the cap.
        content_type: The Content-Type header, if any.
        reply_status: The status code sent back.
    """

    id: UUID
    received_at: datetime
    method: HttpMethod
    path: str
    query_string: str
    body_size: int
    body_truncated: bool
    content_type: str | None
    reply_status: int


@dataclass(slots=True, frozen=True, kw_only=True)
class CapturedRequest:
    """A stored request with every detail.

    Attributes:
        id: The UUIDv7 id, which sorts by time.
        bin_id: The id of the bin that caught it.
        received_at: When the request arrived.
        method: The HTTP method.
        path: The sub-path after the bin id.
        query_string: The raw query string.
        query_params: The query as name-value pairs.
        headers: The headers as name-value pairs.
        body: The body bytes; empty when the body was over the cap.
        body_size: The number of body bytes read.
        body_truncated: Whether the body was over the cap.
        body_preview: The first 4 KiB of the body as text.
        content_type: The Content-Type header, if any.
        remote_addr: The client address, if known.
        http_version: The HTTP version.
        reply_status: The status code sent back.
    """

    id: UUID
    bin_id: str
    received_at: datetime
    method: HttpMethod
    path: str
    query_string: str
    query_params: NameValuePairs
    headers: NameValuePairs
    body: bytes
    body_size: int
    body_truncated: bool
    body_preview: str
    content_type: str | None
    remote_addr: str | None
    http_version: str
    reply_status: int

    def summary(self) -> RequestSummary:
        """Give the short form of this request.

        Returns:
            The summary.
        """
        return RequestSummary(
            id=self.id,
            received_at=self.received_at,
            method=self.method,
            path=self.path,
            query_string=self.query_string,
            body_size=self.body_size,
            body_truncated=self.body_truncated,
            content_type=self.content_type,
            reply_status=self.reply_status,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class ReplayResult:
    """What a target sent back to a replay. It is shown once and never stored.

    Attributes:
        status: The reply status code.
        reason: The reason phrase, if the target sent one.
        elapsed_ms: Milliseconds from sending to the end of the reply, or to the read cap.
        headers: The reply headers, in order.
        body: The reply body, up to the read cap.
        body_truncated: Whether the reply body went on past the read cap.
    """

    status: int
    reason: str
    elapsed_ms: int
    headers: NameValuePairs
    body: bytes
    body_truncated: bool


class EventType(StrEnum):
    """What happened to a bin, as told to open inspectors."""

    REQUEST_CAPTURED = "request.captured"
    REQUEST_DELETED = "request.deleted"
    BIN_UPDATED = "bin.updated"
    BIN_CLEARED = "bin.cleared"
    BIN_DELETED = "bin.deleted"
    RESYNC = "resync"
    """Not published: a bus gives it to a subscriber that missed events, which then reloads."""


@dataclass(slots=True, frozen=True, kw_only=True)
class BinEvent:
    """One event about a bin.

    Attributes:
        type: What happened.
        bin_id: The bin it happened to.
        request: The new request, for `request.captured`.
        request_id: The deleted request's id, for `request.deleted`.
        label: The new label, for `bin.updated`.
    """

    type: EventType
    bin_id: str
    request: RequestSummary | None = None
    request_id: UUID | None = None
    label: str | None = None
