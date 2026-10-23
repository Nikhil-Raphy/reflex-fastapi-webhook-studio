"""Tests for the live-update helpers."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from uuid import uuid7

from reflex_fastapi_webhook_studio.domain import HttpMethod, RequestSummary
from reflex_fastapi_webhook_studio.ui.live import Sockets, merge_request
from reflex_fastapi_webhook_studio.ui.views import request_row
from tests.factories import NOW

if TYPE_CHECKING:
    import reflex as rx


def summary(path: str) -> RequestSummary:
    """Build a request summary.

    Args:
        path: The request path.

    Returns:
        The summary.
    """
    return RequestSummary(
        id=uuid7(),
        received_at=NOW,
        method=HttpMethod.POST,
        path=path,
        query_string="",
        body_size=0,
        body_truncated=False,
        content_type=None,
        reply_status=200,
    )


def test_given_rows_when_new_request_merges_then_it_goes_first_within_limit() -> None:
    """Given two rows and a limit of two, when a new request merges, then it goes first and the oldest drops."""
    # Given
    old, older = summary("/old"), summary("/older")
    rows = [request_row(old), request_row(older)]
    # When
    merged = merge_request(rows, summary("/new"), limit=2)
    # Then
    assert merged is not None
    assert [row.target for row in merged] == ["/new", "/old"]


def test_given_listed_request_when_it_merges_again_then_nothing_changes() -> None:
    """Given a request already listed, when it merges again, then the merge says there is nothing to add."""
    # Given
    known = summary("/known")
    rows = [request_row(known)]
    # When
    merged = merge_request(rows, known, limit=10)
    # Then
    assert merged is None


def test_given_tabs_when_sockets_are_checked_then_only_open_tabs_count() -> None:
    """Given an app with one open tab, when sockets are checked, then only that tab counts, and none before."""
    # Given
    sockets = Sockets()
    before = sockets.connected("open")
    app = SimpleNamespace(event_namespace=SimpleNamespace(token_to_sid={"open": "sid-1"}))
    sockets.attach(cast("rx.App", app))
    # When
    open_tab = sockets.connected("open")
    closed_tab = sockets.connected("closed")
    # Then
    assert (before, open_tab, closed_tab) == (False, True, False)
