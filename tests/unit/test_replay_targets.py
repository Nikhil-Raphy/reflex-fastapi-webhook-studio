"""Tests for the replay target and header rules."""

import pytest

from reflex_fastapi_webhook_studio.domain import ReplayTargetError
from reflex_fastapi_webhook_studio.services.replay import MAX_URL_LENGTH, outbound_headers, target_url


@pytest.mark.parametrize(
    ("raw", "query", "expected"),
    [
        ("https://example.com/hook", "", "https://example.com/hook"),
        ("  http://example.com:8080/a  ", "x=1&x=2", "http://example.com:8080/a?x=1&x=2"),
        ("https://example.com/a?keep=1#part", "x=1", "https://example.com/a?keep=1&x=1"),
        ("https://bücher.example/a", "", "https://xn--bcher-kva.example/a"),
    ],
)
def test_given_target_when_checked_then_original_query_is_added_and_fragment_dropped(
    raw: str, query: str, expected: str
) -> None:
    """Given a target and the original query string, when checked, then the query joins and the fragment goes."""
    # Given
    typed = raw
    # When
    url = target_url(typed, query)
    # Then
    assert url == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "https://user:pw@example.com/",
        "not a url",
        "http://",
        "https://[::1",
    ],
)
def test_given_bad_target_when_checked_then_it_is_refused(raw: str) -> None:
    """Given a target that is not an http or https URL with a host, or that holds a user name, then it is refused."""
    # Given
    typed = raw
    # When / Then
    with pytest.raises(ReplayTargetError):
        target_url(typed, "")


def test_given_very_long_target_when_checked_then_it_is_refused() -> None:
    """Given a target longer than the cap, when checked, then it is refused."""
    # Given
    typed = "https://example.com/" + "a" * MAX_URL_LENGTH
    # When / Then
    with pytest.raises(ReplayTargetError):
        target_url(typed, "")


def test_given_captured_headers_when_replayed_then_hop_by_hop_host_and_length_are_dropped() -> None:
    """Given captured headers, when chosen for a replay, then hop-by-hop ones, Host and Content-Length go."""
    # Given
    headers = (
        ("Host", "old.example.com"),
        ("Content-Length", "3"),
        ("Connection", "keep-alive, X-Hop"),
        ("Keep-Alive", "timeout=5"),
        ("Transfer-Encoding", "chunked"),
        ("X-Hop", "1"),
        ("Authorization", "Bearer x"),
        ("X-A", "1"),
        ("X-A", "2"),
    )
    # When
    sent = outbound_headers(headers)
    # Then
    assert sent == [("Authorization", "Bearer x"), ("X-A", "1"), ("X-A", "2")]
