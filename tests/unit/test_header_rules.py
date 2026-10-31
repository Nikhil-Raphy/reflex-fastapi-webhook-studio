"""Tests for the header rules of a bin's reply."""

import pytest

from reflex_fastapi_webhook_studio.security.header_rules import (
    connection_listed,
    is_field_value,
    is_token,
    reply_header_problem,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("X-Request-Id", True), ("x_custom.v2~!", True), ("Bad Name", False), ("bad:name", False), ("", False)],
)
def test_given_header_name_when_checked_then_only_tokens_pass(name: str, expected: bool) -> None:  # noqa: FBT001
    """Given a header name, when checked, then only RFC 9110 tokens pass."""
    # Given
    candidate = name
    # When
    result = is_token(candidate)
    # Then
    assert result is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("plain\tvalue", True), ("a\r\nSet-Cookie: x", False), ("a\nb", False), ("nul\x00", False), ("x" * 4097, False)],
)
def test_given_header_value_when_checked_then_line_breaks_and_controls_fail(value: str, expected: bool) -> None:  # noqa: FBT001
    """Given a header value, when checked, then CR, LF, other controls and long values fail; a tab passes."""
    # Given
    candidate = value
    # When
    result = is_field_value(candidate)
    # Then
    assert result is expected


@pytest.mark.parametrize(
    ("name", "value", "found"),
    [
        ("X-Teapot", "yes", None),
        ("Set-Cookie", "a=b", "may not set"),
        ("content-security-policy", "none", "may not set"),
        ("Content-Length", "3", "may not set"),
        ("Content-Type", "text/html", "may not set"),
        ("Transfer-Encoding", "chunked", "may not set"),
        ("Access-Control-Allow-Credentials", "true", "may not set"),
        ("X-Ok", "line\r\nbreak", "line break"),
        ("Bad Name", "x", "not a valid header name"),
    ],
)
def test_given_reply_header_when_checked_then_reserved_and_broken_ones_are_named(
    name: str, value: str, found: str | None
) -> None:
    """Given a header for a bin's reply, when checked, then reserved, hop-by-hop and broken headers are refused."""
    # Given
    header = (name, value)
    # When
    problem = reply_header_problem(*header)
    # Then
    if found is None:
        assert problem is None
    else:
        assert problem is not None
        assert found in problem


def test_given_connection_header_when_read_then_named_headers_are_listed() -> None:
    """Given a Connection header that names other headers, when read, then those names come back in lower case."""
    # Given
    headers = (("Connection", "keep-alive, X-Hop , "), ("x-other", "1"))
    # When
    listed = connection_listed(headers)
    # Then
    assert listed == {"keep-alive", "x-hop"}
