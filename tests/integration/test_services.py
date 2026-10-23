"""Tests for the bin, request and capture services, on SQLite and PostgreSQL."""

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid7

import pytest

from reflex_fastapi_webhook_studio.domain import (
    BinLimitError,
    BinNotFoundError,
    HttpMethod,
    IncomingRequest,
    RequestNotFoundError,
)
from reflex_fastapi_webhook_studio.services.bins import BinService
from reflex_fastapi_webhook_studio.services.capture import CaptureService
from reflex_fastapi_webhook_studio.services.requests import RequestService
from reflex_fastapi_webhook_studio.settings import Settings
from tests.factories import NOW

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.db.engine import Database

SETTINGS = Settings(max_bins=2, max_requests_per_bin=3, bin_ttl_days=7)
INCOMING = IncomingRequest(
    method=HttpMethod.POST,
    path="/a/b",
    query_string="x=1&x=2&empty=",
    headers=(("content-type", "application/json"), ("x-a", "1"), ("x-a", "2")),
    body=b'{"ok": true}',
    body_size=12,
    body_truncated=False,
    content_type="application/json",
    remote_addr="203.0.113.7",
    http_version="1.1",
)


@pytest.mark.anyio
async def test_given_room_for_bins_when_bin_is_created_then_it_expires_after_ttl(database: Database) -> None:
    """Given room for more bins, when one is created, then it has a valid id and expires 7 days later."""
    # Given
    bins = BinService(database, SETTINGS, clock=lambda: NOW)
    # When
    bin_ = await bins.create("orders")
    # Then
    assert await bins.get(bin_.id) == bin_
    assert bin_.label == "orders"
    assert bin_.expires_at == NOW + timedelta(days=7)


@pytest.mark.anyio
async def test_given_bin_cap_reached_when_bin_is_created_then_limit_error(database: Database) -> None:
    """Given the app holds the most bins it may, when one more is created, then a limit error is raised."""
    # Given
    bins = BinService(database, SETTINGS, clock=lambda: NOW)
    await bins.create(None)
    await bins.create(None)
    # When / Then
    with pytest.raises(BinLimitError):
        await bins.create(None)


@pytest.mark.anyio
@pytest.mark.parametrize("bin_id", ["AbCdEfGhIjKlMnOpQrStUv", "not-a-bin-id"])
async def test_given_unknown_or_malformed_id_when_bin_is_read_then_not_found(database: Database, bin_id: str) -> None:
    """Given an unknown or malformed bin id, when the bin is read or renamed, then it is not found."""
    # Given
    bins = BinService(database, SETTINGS, clock=lambda: NOW)
    # When / Then
    with pytest.raises(BinNotFoundError):
        await bins.get(bin_id)
    with pytest.raises(BinNotFoundError):
        await bins.rename(bin_id, "new")


@pytest.mark.anyio
async def test_given_bin_when_renamed_then_new_label_is_kept(database: Database) -> None:
    """Given a bin, when it is renamed, then the new label is kept."""
    # Given
    bins = BinService(database, SETTINGS, clock=lambda: NOW)
    bin_ = await bins.create("old")
    # When
    renamed = await bins.rename(bin_.id, "new")
    # Then
    assert renamed == replace(bin_, label="new")


@pytest.mark.anyio
async def test_given_bin_when_request_is_captured_then_it_is_stored_and_expiry_moves(database: Database) -> None:
    """Given a bin, when a request is captured an hour later, then it is stored in full and the expiry moves out."""
    # Given
    bin_ = await BinService(database, SETTINGS, clock=lambda: NOW).create(None)
    later = NOW + timedelta(hours=1)
    capture = CaptureService(database, SETTINGS, clock=lambda: later)
    # When
    stored = await capture.capture(bin_.id, INCOMING, reply_status=200)
    # Then
    assert await RequestService(database).get(bin_.id, stored.id) == stored
    assert stored.query_params == (("x", "1"), ("x", "2"), ("empty", ""))
    assert stored.headers == INCOMING.headers
    assert stored.body_preview == '{"ok": true}'
    assert stored.received_at == later
    moved = await BinService(database, SETTINGS).get(bin_.id)
    assert (moved.last_activity_at, moved.expires_at) == (later, later + timedelta(days=7))


@pytest.mark.anyio
async def test_given_nul_in_path_and_query_when_captured_then_stored_with_replacement(database: Database) -> None:
    """Given a path and query holding NUL, when captured, then they are stored with NUL replaced."""
    # Given
    bin_ = await BinService(database, SETTINGS, clock=lambda: NOW).create(None)
    incoming = replace(INCOMING, path="/a\x00b", query_string="q=%00")
    # When
    stored = await CaptureService(database, SETTINGS, clock=lambda: NOW).capture(bin_.id, incoming, reply_status=200)
    # Then
    assert stored.path == "/a\ufffdb"
    assert stored.query_params == (("q", "\ufffd"),)


@pytest.mark.anyio
async def test_given_full_bin_when_request_is_captured_then_oldest_is_dropped(database: Database) -> None:
    """Given a bin at its request cap, when one more arrives, then the oldest is gone and the cap still holds."""
    # Given
    bin_ = await BinService(database, SETTINGS, clock=lambda: NOW).create(None)
    capture = CaptureService(database, SETTINGS, clock=lambda: NOW)
    first = await capture.capture(bin_.id, INCOMING, reply_status=200)
    for _ in range(2):
        await capture.capture(bin_.id, INCOMING, reply_status=200)
    # When
    await capture.capture(bin_.id, INCOMING, reply_status=200)
    # Then
    rows = await RequestService(database).list(bin_.id, limit=10)
    assert len(rows) == SETTINGS.max_requests_per_bin
    assert first.id not in {row.id for row in rows}


@pytest.mark.anyio
async def test_given_unknown_bin_when_request_is_captured_then_not_found(database: Database) -> None:
    """Given no bin with an id, when a request is captured for it, then the bin is not found."""
    # Given
    capture = CaptureService(database, SETTINGS, clock=lambda: NOW)
    # When / Then
    with pytest.raises(BinNotFoundError):
        await capture.capture("AbCdEfGhIjKlMnOpQrStUv", INCOMING, reply_status=200)


@pytest.mark.anyio
async def test_given_unknown_bin_or_request_when_read_then_not_found(database: Database) -> None:
    """Given an unknown bin or request, when requests are read, then the right not-found error is raised."""
    # Given
    bin_ = await BinService(database, SETTINGS, clock=lambda: NOW).create(None)
    requests = RequestService(database)
    # When / Then
    with pytest.raises(BinNotFoundError):
        await requests.list("AbCdEfGhIjKlMnOpQrStUv", limit=10)
    with pytest.raises(BinNotFoundError):
        await requests.get("bad", uuid7())
    with pytest.raises(RequestNotFoundError):
        await requests.get(bin_.id, uuid7())
