"""Tests for the shared value types."""

from reflex_fastapi_webhook_studio.domain import (
    BIN_ID_LENGTH,
    PREVIEW_BYTES,
    HttpMethod,
    body_preview,
    is_bin_id,
    new_bin_id,
    storable_text,
)


def test_given_text_with_nul_when_made_storable_then_nul_becomes_replacement_character() -> None:
    """Given text holding NUL, when it is made storable, then each NUL becomes U+FFFD."""
    # Given
    value = "a\x00b\x00"
    # When
    stored = storable_text(value)
    # Then
    assert stored == "a\ufffdb\ufffd"


def test_given_long_binary_body_when_previewed_then_text_is_capped_and_safe() -> None:
    """Given a body over 4 KiB with NUL and bad UTF-8, when previewed, then the text covers 4 KiB with both replaced."""
    # Given
    body = b"\x00\xff" + b"a" * (PREVIEW_BYTES * 2)
    # When
    preview = body_preview(body)
    # Then
    assert preview.startswith("\ufffd\ufffda")
    assert len(preview) == PREVIEW_BYTES
    assert "\x00" not in preview


def test_given_new_bin_id_when_checked_then_it_is_valid_and_22_characters() -> None:
    """Given a freshly made bin id, when it is checked, then it is valid and 22 characters long."""
    # Given
    bin_id = new_bin_id()
    # When
    valid = is_bin_id(bin_id)
    # Then
    assert valid
    assert len(bin_id) == BIN_ID_LENGTH == 22


def test_given_two_new_bin_ids_when_compared_then_they_differ() -> None:
    """Given two freshly made bin ids, when they are compared, then they differ."""
    # Given
    first, second = new_bin_id(), new_bin_id()
    # When
    same = first == second
    # Then
    assert not same


def test_given_malformed_ids_when_checked_then_none_is_valid() -> None:
    """Given ids of the wrong length or with other characters, when checked, then none is valid."""
    # Given
    ids = ["short", "A" * 23, "A" * 21 + "!", "A" * 21 + "/", ""]
    # When
    results = [is_bin_id(value) for value in ids]
    # Then
    assert not any(results)


def test_given_http_methods_when_listed_then_only_captured_methods_appear() -> None:
    """Given the method enum, when listed, then it holds the seven captured methods and not TRACE or CONNECT."""
    # Given
    methods = {method.value for method in HttpMethod}
    # When
    missing = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} - methods
    # Then
    assert not missing
    assert "TRACE" not in methods
    assert "CONNECT" not in methods
