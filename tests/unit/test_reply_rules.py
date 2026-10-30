"""Tests for the rules a bin's reply settings must keep."""

import pytest

from reflex_fastapi_webhook_studio.domain import ReplyConfig
from reflex_fastapi_webhook_studio.services.bins import reply_problem

MAX_DELAY_MS = 1000


@pytest.mark.parametrize(
    ("reply", "found"),
    [
        (ReplyConfig(), None),
        (ReplyConfig(status=418, content_type="text/plain", headers=(("X-Tea", "yes"),), body="", delay_ms=1000), None),
        (ReplyConfig(status=204), None),
        (ReplyConfig(status=199), "status must be from 200 to 599"),
        (ReplyConfig(status=600), "status must be from 200 to 599"),
        (ReplyConfig(delay_ms=1001), "delay must be from 0 to 1000"),
        (ReplyConfig(delay_ms=-1), "delay must be from 0 to 1000"),
        (ReplyConfig(status=304, body="x"), "A 304 reply has no body"),
        (ReplyConfig(body="x" * 65_537), "at most 64 KiB"),
        (ReplyConfig(content_type=""), "content type"),
        (ReplyConfig(content_type="text/plain\r\nX-Bad: 1"), "content type"),
        (ReplyConfig(headers=tuple((f"X-{n}", "1") for n in range(33))), "at most 32 headers"),
        (ReplyConfig(headers=(("Set-Cookie", "a=b"),)), "may not set Set-Cookie"),
        (ReplyConfig(headers=(("X-Ok", "a\nb"),)), "line break"),
    ],
)
def test_given_reply_settings_when_checked_then_each_broken_rule_is_named(
    reply: ReplyConfig, found: str | None
) -> None:
    """Given reply settings, when checked, then allowed ones pass and each broken rule is named."""
    # Given
    settings = reply
    # When
    problem = reply_problem(settings, max_delay_ms=MAX_DELAY_MS)
    # Then
    if found is None:
        assert problem is None
    else:
        assert problem is not None
        assert found in problem
