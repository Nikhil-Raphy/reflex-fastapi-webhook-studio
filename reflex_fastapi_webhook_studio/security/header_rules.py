"""Rules for the headers a user may set on a bin's reply, and the headers that belong to one hop only."""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.domain import NameValuePairs

# RFC 9110, section 7.6.1: these describe one connection, so a proxy or a replay must not pass them on.
HOP_BY_HOP = frozenset({"connection", "proxy-connection", "keep-alive", "te", "transfer-encoding", "upgrade"})
# The app sets these itself, or they would break the reply or its safety headers.
RESERVED = frozenset(
    {
        "content-length",
        "content-security-policy",
        "content-type",
        "set-cookie",
        "x-content-type-options",
    }
)
RESERVED_PREFIX = "access-control-"
MAX_NAME_LENGTH = 256
MAX_VALUE_LENGTH = 4096

_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
# Control characters other than horizontal tab, which RFC 9110 field values may not hold.
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def is_token(name: str) -> bool:
    """Check that a header name is an RFC 9110 token.

    Args:
        name: The header name.

    Returns:
        Whether the name is a token.
    """
    return _TOKEN.fullmatch(name) is not None


def is_field_value(value: str) -> bool:
    """Check that a header value holds no line break or other control character, and is not too long.

    Args:
        value: The header value.

    Returns:
        Whether a header may carry the value.
    """
    return _CONTROL.search(value) is None and len(value) <= MAX_VALUE_LENGTH


def reply_header_problem(name: str, value: str) -> str | None:
    """Check one header that a user wants a bin's reply to carry.

    Args:
        name: The header name.
        value: The header value.

    Returns:
        What is wrong with the header, or None if the reply may carry it.
    """
    lowered = name.lower()
    if not is_token(name) or len(name) > MAX_NAME_LENGTH:
        return f"{name!r} is not a valid header name."
    if not is_field_value(value):
        return f"The value of {name} holds a line break or another control character, or is too long."
    if lowered in HOP_BY_HOP or lowered in RESERVED or lowered.startswith(RESERVED_PREFIX):
        return f"A reply may not set {name}."
    return None


def connection_listed(headers: NameValuePairs) -> frozenset[str]:
    """Find the extra hop-by-hop headers that a request's Connection header names.

    Args:
        headers: The request headers.

    Returns:
        The named headers, in lower case.
    """
    return frozenset(
        option.strip().lower()
        for name, value in headers
        if name.lower() == "connection"
        for option in value.split(",")
        if option.strip()
    )
