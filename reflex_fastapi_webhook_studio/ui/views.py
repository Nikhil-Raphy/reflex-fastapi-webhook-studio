"""Turn domain values into the plain records that UI state holds, and parse what users type."""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl

from reflex_fastapi_webhook_studio.domain import BinSummary, CapturedRequest, RequestSummary, is_bin_id
from reflex_fastapi_webhook_studio.security.masking import is_secret_header

_BIN_ID_IN_TEXT = re.compile(r"(?:/api/webhook/|/bins/)([A-Za-z0-9_-]{22})(?:[/?#]|$)")
_JSON_STARTS = ("{", "[")
SHORT_ID_LENGTH = 6
NO_LABEL = "No label"


@dataclass(slots=True, frozen=True, kw_only=True)
class BinRowView:
    """One bin in the home page list.

    Attributes:
        id: The bin id.
        href: The inspector page for the bin.
        short_id: The first characters of the id, for display.
        label: The label, or "No label".
        request_count: How many requests the bin holds.
        last_activity_at: When the bin last caught a request, as ISO 8601.
    """

    id: str
    href: str
    short_id: str
    label: str
    request_count: int
    last_activity_at: str


@dataclass(slots=True, frozen=True, kw_only=True)
class RequestRowView:
    """One request in the inspector list.

    Attributes:
        id: The request id.
        method: The HTTP method.
        target: The sub-path after the bin id, with "?" and the query string when there is one.
        received_at: When it arrived, as ISO 8601.
    """

    id: str
    method: str
    target: str
    received_at: str


@dataclass(slots=True, frozen=True, kw_only=True)
class PairView:
    """A header, query or form field.

    Attributes:
        index: The position in its list, which the UI uses to reveal a masked value.
        name: The name.
        value: The value.
        secret: Whether the UI masks the value until clicked.
    """

    index: int
    name: str
    value: str
    secret: bool = False


@dataclass(slots=True, frozen=True, kw_only=True)
class RequestView:
    """A request with every detail the inspector tabs show.

    Attributes:
        id: The request id; empty when nothing is picked.
        method: The HTTP method.
        target: The sub-path after the bin id, with "?" and the query string when there is one.
        path: The sub-path after the bin id.
        query_string: The raw query string.
        received_at: When it arrived, as ISO 8601.
        body_size: The number of body bytes read.
        content_type: The Content-Type header, or an empty string.
        remote_addr: The client address, or an empty string.
        http_version: The HTTP version.
        reply_status: The status code sent back.
        headers: The headers in the order they came.
        query_params: The query fields in the order they came.
        body_kind: How the Body tab shows the body: empty, truncated, json, form, text or binary.
        body_text: Formatted JSON or the text, for the json and text kinds.
        form_fields: The fields, for the form kind.
    """

    id: str = ""
    method: str = ""
    target: str = ""
    path: str = ""
    query_string: str = ""
    received_at: str = ""
    body_size: int = 0
    content_type: str = ""
    remote_addr: str = ""
    http_version: str = ""
    reply_status: int = 0
    headers: list[PairView] = field(default_factory=list)
    query_params: list[PairView] = field(default_factory=list)
    body_kind: str = "empty"
    body_text: str = ""
    form_fields: list[PairView] = field(default_factory=list)


def bin_row(summary: BinSummary) -> BinRowView:
    """Build a home page row.

    Args:
        summary: The bin.

    Returns:
        The row.
    """
    return BinRowView(
        id=summary.id,
        href=f"/bins/{summary.id}",
        short_id=f"{summary.id[:SHORT_ID_LENGTH]}…",
        label=summary.label or NO_LABEL,
        request_count=summary.request_count,
        last_activity_at=summary.last_activity_at.isoformat(),
    )


def request_row(summary: RequestSummary) -> RequestRowView:
    """Build an inspector list row.

    Args:
        summary: The request.

    Returns:
        The row.
    """
    return RequestRowView(
        id=str(summary.id),
        method=summary.method.value,
        target=_target(summary.path, summary.query_string),
        received_at=summary.received_at.isoformat(),
    )


def request_view(request: CapturedRequest) -> RequestView:
    """Build the record behind the inspector tabs.

    Args:
        request: The stored request.

    Returns:
        The record.
    """
    kind, text, form = body_view(request.body, request.content_type, truncated=request.body_truncated)
    return RequestView(
        id=str(request.id),
        method=request.method.value,
        target=_target(request.path, request.query_string),
        path=request.path,
        query_string=request.query_string,
        received_at=request.received_at.isoformat(),
        body_size=request.body_size,
        content_type=request.content_type or "",
        remote_addr=request.remote_addr or "",
        http_version=request.http_version,
        reply_status=request.reply_status,
        headers=[
            PairView(index=index, name=name, value=value, secret=is_secret_header(name))
            for index, (name, value) in enumerate(request.headers)
        ],
        query_params=[
            PairView(index=index, name=name, value=value) for index, (name, value) in enumerate(request.query_params)
        ],
        body_kind=kind,
        body_text=text,
        form_fields=form,
    )


def _target(path: str, query_string: str) -> str:
    return f"{path}?{query_string}" if query_string else path


def body_view(body: bytes, content_type: str | None, *, truncated: bool) -> tuple[str, str, list[PairView]]:
    """Decide how the Body tab shows a body. It never renders the body as HTML.

    Args:
        body: The body bytes.
        content_type: The Content-Type header, if any.
        truncated: Whether the body was over the cap and not kept.

    Returns:
        The kind (empty, truncated, json, form, text or binary), the text to show, and the form fields.
    """
    if truncated:
        return "truncated", "", []
    if not body:
        return "empty", "", []
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", "", []
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if "json" in media_type or text.lstrip().startswith(_JSON_STARTS):
        try:
            return "json", json.dumps(json.loads(text), indent=2, ensure_ascii=False), []
        except ValueError:
            pass
    if media_type == "application/x-www-form-urlencoded":
        fields = parse_qsl(text, keep_blank_values=True)
        return "form", "", [PairView(index=index, name=name, value=value) for index, (name, value) in enumerate(fields)]
    return "text", text, []


def parse_bin_id(text: str) -> str | None:
    """Find a bin id in what a user typed: the id itself, a capture URL or an inspector URL.

    Args:
        text: The typed text.

    Returns:
        The bin id, or None if the text holds none.
    """
    text = text.strip()
    if is_bin_id(text):
        return text
    found = _BIN_ID_IN_TEXT.search(text)
    return found.group(1) if found else None


def capture_url(api_url: str, bin_id: str) -> str:
    """Build the URL that senders use for a bin.

    Args:
        api_url: The address the app's backend answers on, such as Reflex's `api_url`.
        bin_id: The bin id.

    Returns:
        The capture URL.
    """
    return f"{api_url.rstrip('/')}/api/webhook/{bin_id}"


def curl_example(url: str) -> str:
    """Build a curl command that sends a small JSON body to a URL.

    Args:
        url: The capture URL.

    Returns:
        The command.
    """
    return f"curl -X POST {url} -H 'content-type: application/json' -d '{{\"hello\": \"world\"}}'"


def known_ids(stored: str) -> list[str]:
    """Read the bin ids a browser remembers.

    Args:
        stored: The JSON list kept in the browser's local storage.

    Returns:
        The well-formed ids, newest first; an empty list if the value is not a JSON list.
    """
    try:
        values = json.loads(stored)
    except ValueError:
        return []
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and is_bin_id(value)]


def remember(stored: str, bin_id: str, *, limit: int) -> str:
    """Add a bin id to the front of the list a browser remembers.

    Args:
        stored: The JSON list kept in the browser's local storage.
        bin_id: The id to add.
        limit: The most ids to keep; the oldest go first.

    Returns:
        The new JSON list.
    """
    ids = [bin_id, *(value for value in known_ids(stored) if value != bin_id)]
    return json.dumps(ids[:limit])
