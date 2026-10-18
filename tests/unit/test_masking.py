"""Tests for which headers the UI masks."""

import pytest

from reflex_fastapi_webhook_studio.security.masking import is_secret_header


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "proxy-authorization",
        "Cookie",
        "set-cookie",
        "X-Auth-Token",
        "X-Hub-Signature-256",
        "Stripe-Signature",
        "X-Api-Key",
        "apikey",
        "X-API_KEY",
        "client-secret",
        "X-Password",
        "X-Session-Id",
    ],
)
def test_given_secret_header_name_when_checked_then_it_is_masked(name: str) -> None:
    """Given a header name that carries a secret, when checked, then the UI masks it."""
    # Given
    header = name
    # When
    secret = is_secret_header(header)
    # Then
    assert secret


@pytest.mark.parametrize("name", ["Content-Type", "User-Agent", "X-GitHub-Event", "Accept"])
def test_given_plain_header_name_when_checked_then_it_shows(name: str) -> None:
    """Given a header name with no secret, when checked, then the UI shows its value."""
    # Given
    header = name
    # When
    secret = is_secret_header(header)
    # Then
    assert not secret
