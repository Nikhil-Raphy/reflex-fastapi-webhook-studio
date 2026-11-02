"""Tests for the bin, request, capture, export and sweeper services, on SQLite and PostgreSQL."""

import asyncio
import base64
import json
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid7

import pytest

from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus
from reflex_fastapi_webhook_studio.domain import (
    MAX_CONTENT_TYPE_LENGTH,
    BinEvent,
    BinLimitError,
    BinListing,
    BinNotFoundError,
    EventType,
    HttpMethod,
    IncomingRequest,
    InvalidReplyError,
    ListingOffError,
    ReplyConfig,
    RequestNotFoundError,
)
from reflex_fastapi_webhook_studio.services.bins import BinService
from reflex_fastapi_webhook_studio.services.capture import CaptureService
from reflex_fastapi_webhook_studio.services.export import BATCH_SIZE, ExportService
from reflex_fastapi_webhook_studio.services.requests import RequestService
from reflex_fastapi_webhook_studio.services.sweeper import Sweeper, jittered
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
async def test_given_long_content_type_when_captured_then_it_is_cut_to_fit(database: Database) -> None:
    """Given a 300-character Content-Type, when captured, then the first 255 are kept and the header stays whole."""
    # Given
    bin_ = await BinService(database, SETTINGS, clock=lambda: NOW).create(None)
    long_type = f"text/plain; x={'a' * 286}"
    incoming = replace(INCOMING, headers=(("content-type", long_type),), content_type=long_type)
    # When
    stored = await CaptureService(database, SETTINGS, clock=lambda: NOW).capture(bin_.id, incoming, reply_status=200)
    # Then
    assert await RequestService(database).get(bin_.id, stored.id) == stored
    assert stored.content_type == long_type[:MAX_CONTENT_TYPE_LENGTH]
    assert stored.headers == (("content-type", long_type),)


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


@pytest.mark.anyio
async def test_given_all_listing_when_bins_are_listed_then_most_active_come_first_with_counts(
    database: Database,
) -> None:
    """Given `all` listing and two bins, when every bin is listed, then the busier one comes first with its count."""
    # Given
    settings = replace(SETTINGS, bin_listing=BinListing.ALL)
    quiet = await BinService(database, settings, clock=lambda: NOW).create("quiet")
    busy = await BinService(database, settings, clock=lambda: NOW).create("busy")
    capture = CaptureService(database, settings, clock=lambda: NOW + timedelta(minutes=5))
    for _ in range(2):
        await capture.capture(busy.id, INCOMING, reply_status=200)
    # When
    listed = await BinService(database, settings).list_all()
    # Then
    assert [(row.id, row.label, row.request_count) for row in listed] == [(busy.id, "busy", 2), (quiet.id, "quiet", 0)]
    assert listed[0].last_activity_at == NOW + timedelta(minutes=5)


@pytest.mark.anyio
async def test_given_browser_listing_when_every_bin_is_listed_then_listing_is_off(database: Database) -> None:
    """Given `browser` listing, when every bin is listed, then the service refuses."""
    # Given
    bins = BinService(database, SETTINGS)
    # When / Then
    with pytest.raises(ListingOffError):
        await bins.list_all()


@pytest.mark.anyio
async def test_given_known_ids_when_summaries_are_read_then_only_existing_bins_return(database: Database) -> None:
    """Given ids a browser remembers, some unknown or malformed, when summaries are read, then only real bins return."""
    # Given
    bins = BinService(database, SETTINGS, clock=lambda: NOW)
    kept = await bins.create("kept")
    await bins.create("not asked for")
    # When
    listed = await bins.summaries([kept.id, "AbCdEfGhIjKlMnOpQrStUv", "bad", kept.id])
    none = await bins.summaries(["bad"])
    # Then
    assert [row.id for row in listed] == [kept.id]
    assert none == []


@pytest.mark.anyio
async def test_given_subscriber_when_request_is_captured_or_bin_renamed_then_events_arrive(database: Database) -> None:
    """Given a subscriber of a bin, when a request is captured and the bin renamed, then both events arrive."""
    # Given
    bus = MemoryBus()
    bins = BinService(database, SETTINGS, bus=bus, clock=lambda: NOW)
    bin_ = await bins.create("old")
    async with bus.subscribe(bin_.id) as events:
        # When
        stored = await CaptureService(database, SETTINGS, bus=bus).capture(bin_.id, INCOMING, reply_status=200)
        await bins.rename(bin_.id, "new")
        got = [await events.next(1), await events.next(1)]
    # Then
    assert got == [
        BinEvent(type=EventType.REQUEST_CAPTURED, bin_id=bin_.id, request=stored.summary()),
        BinEvent(type=EventType.BIN_UPDATED, bin_id=bin_.id, label="new"),
    ]


@pytest.mark.anyio
async def test_given_subscriber_when_requests_and_bin_are_deleted_then_each_event_arrives(database: Database) -> None:
    """Given a subscriber of a bin, when a request is deleted, the bin cleared and then deleted, each event arrives."""
    # Given
    bus = MemoryBus()
    bins = BinService(database, SETTINGS, bus=bus, clock=lambda: NOW)
    requests = RequestService(database, bus=bus)
    bin_ = await bins.create(None)
    capture = CaptureService(database, SETTINGS)
    first = await capture.capture(bin_.id, INCOMING, reply_status=200)
    await capture.capture(bin_.id, INCOMING, reply_status=200)
    async with bus.subscribe(bin_.id) as events:
        # When
        await requests.delete(bin_.id, first.id)
        count_after_delete = await requests.count(bin_.id)
        await requests.clear(bin_.id)
        count_after_clear = await requests.count(bin_.id)
        await bins.delete(bin_.id)
        got = [await events.next(1) for _ in range(3)]
    # Then
    assert (count_after_delete, count_after_clear) == (1, 0)
    assert got == [
        BinEvent(type=EventType.REQUEST_DELETED, bin_id=bin_.id, request_id=first.id),
        BinEvent(type=EventType.BIN_CLEARED, bin_id=bin_.id),
        BinEvent(type=EventType.BIN_DELETED, bin_id=bin_.id),
    ]
    with pytest.raises(BinNotFoundError):
        await bins.get(bin_.id)


@pytest.mark.anyio
async def test_given_gone_bin_or_request_when_deleted_then_not_found(database: Database) -> None:
    """Given an unknown bin or request, when it is deleted or cleared, then the right not-found error is raised."""
    # Given
    bins = BinService(database, SETTINGS)
    requests = RequestService(database)
    bin_ = await bins.create(None)
    # When / Then
    with pytest.raises(RequestNotFoundError):
        await requests.delete(bin_.id, uuid7())
    with pytest.raises(BinNotFoundError):
        await requests.delete("bad", uuid7())
    with pytest.raises(BinNotFoundError):
        await requests.clear("AbCdEfGhIjKlMnOpQrStUv")
    with pytest.raises(BinNotFoundError):
        await bins.delete("AbCdEfGhIjKlMnOpQrStUv")
    with pytest.raises(BinNotFoundError):
        await bins.delete("bad")


@pytest.mark.anyio
async def test_given_bin_when_reply_is_set_then_it_is_kept_and_open_pages_are_told(database: Database) -> None:
    """Given a bin, when good reply settings are set, then they are kept and a bin.updated event goes out."""
    # Given
    bus = MemoryBus()
    bins = BinService(database, SETTINGS, bus=bus)
    bin_ = await bins.create("orders")
    reply = ReplyConfig(status=418, headers=(("X-Tea", "yes"),), body="short and stout", delay_ms=10)
    async with bus.subscribe(bin_.id) as events:
        # When
        updated = await bins.set_reply(bin_.id, reply)
        event = await events.next(1)
    # Then
    assert updated.reply == reply == (await bins.get(bin_.id)).reply
    assert event == BinEvent(type=EventType.BIN_UPDATED, bin_id=bin_.id, label="orders")


@pytest.mark.anyio
async def test_given_bad_reply_or_unknown_bin_when_reply_is_set_then_it_is_refused(database: Database) -> None:
    """Given reply settings that break a rule, or an unknown bin, when set, then nothing changes."""
    # Given
    bins = BinService(database, SETTINGS)
    bin_ = await bins.create(None)
    # When / Then
    with pytest.raises(InvalidReplyError, match="may not set Set-Cookie"):
        await bins.set_reply(bin_.id, ReplyConfig(headers=(("Set-Cookie", "a=b"),)))
    with pytest.raises(InvalidReplyError, match="delay"):
        await bins.set_reply(bin_.id, ReplyConfig(delay_ms=SETTINGS.max_delay_ms + 1))
    with pytest.raises(BinNotFoundError):
        await bins.set_reply("AbCdEfGhIjKlMnOpQrStUv", ReplyConfig())
    assert (await bins.get(bin_.id)).reply == ReplyConfig()


@pytest.mark.anyio
async def test_given_bin_last_used_eight_days_ago_when_sweeper_runs_then_it_is_gone(database: Database) -> None:
    """Given a bin last used eight days ago and a fresh one, when the sweeper runs, then only the old one goes."""
    # Given
    bus = MemoryBus()
    old = await BinService(database, SETTINGS, clock=lambda: NOW - timedelta(days=8)).create("old")
    fresh = await BinService(database, SETTINGS, clock=lambda: NOW).create("fresh")
    stale = await CaptureService(database, SETTINGS, clock=lambda: NOW - timedelta(days=8)).capture(
        old.id, INCOMING, reply_status=200
    )
    sweeper = Sweeper(database, 3600, bus=bus, clock=lambda: NOW)
    async with bus.subscribe(old.id) as events:
        # When
        deleted = await sweeper.sweep()
        again = await sweeper.sweep()
        event = await events.next(1)
    # Then
    assert (deleted, again) == ([old.id], [])
    assert event == BinEvent(type=EventType.BIN_DELETED, bin_id=old.id)
    assert (await BinService(database, SETTINGS).get(fresh.id)).label == "fresh"
    with pytest.raises(RequestNotFoundError):
        await RequestService(database).get(old.id, stale.id)


@pytest.mark.anyio
async def test_given_running_sweeper_when_time_passes_then_it_sweeps_and_survives_errors(database: Database) -> None:
    """Given a sweeper running on a short timer, when a sweep fails once, then it logs it and keeps sweeping."""
    # Given
    expired = await BinService(database, SETTINGS, clock=lambda: NOW - timedelta(days=8)).create(None)
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 1:
            raise OSError
        return NOW

    sweeper = Sweeper(database, 0.01, clock=clock, vary=lambda seconds: seconds)
    bins = BinService(database, SETTINGS)
    # When
    async with sweeper.run():
        for _ in range(300):
            await asyncio.sleep(0.01)
            if not await bins.summaries([expired.id]):
                break
    # Then
    assert clock_calls >= 2
    assert not await bins.summaries([expired.id])


def test_given_planned_wait_when_jittered_then_it_stays_within_ten_percent() -> None:
    """Given a planned wait, when varied, then each result lies within 10% of it."""
    # Given
    planned = 100.0
    # When
    waits = [jittered(planned) for _ in range(50)]
    # Then
    assert all(90.0 <= wait <= 110.0 for wait in waits)


@pytest.mark.anyio
async def test_given_bin_with_requests_when_exported_then_the_file_holds_every_request(database: Database) -> None:
    """Given a bin with a text and a binary request, when exported, then the JSON holds both, oldest first."""
    # Given
    bins = BinService(database, SETTINGS, clock=lambda: NOW)
    bin_ = await bins.create("orders")
    capture = CaptureService(database, replace(SETTINGS, max_requests_per_bin=100), clock=lambda: NOW)
    text = await capture.capture(bin_.id, INCOMING, reply_status=200)
    binary = await capture.capture(bin_.id, replace(INCOMING, body=b"\xff\x00", body_size=2), reply_status=201)
    more = [await capture.capture(bin_.id, INCOMING, reply_status=200) for _ in range(BATCH_SIZE)]
    exports = ExportService(database, clock=lambda: NOW)
    # When
    chunks = await exports.export(bin_.id)
    document = json.loads(b"".join([chunk async for chunk in chunks]))
    # Then
    assert (document["format"], document["version"], document["exported_at"]) == (
        "webhook-studio-export",
        1,
        "2026-10-13T12:00:00Z",
    )
    assert document["bin"]["label"] == "orders"
    assert document["bin"]["reply"]["status"] == 200
    entries = document["requests"]
    assert [entry["id"] for entry in entries] == [str(r.id) for r in (text, binary, *more)]
    assert entries[0]["body_text"] == '{"ok": true}'
    assert base64.b64decode(entries[1]["body_base64"]) == b"\xff\x00"
    assert "body_text" not in entries[1]
    assert entries[1]["reply_status"] == 201


@pytest.mark.anyio
@pytest.mark.parametrize("bin_id", ["AbCdEfGhIjKlMnOpQrStUv", "bad"])
async def test_given_unknown_bin_when_exported_then_not_found_before_any_chunk(database: Database, bin_id: str) -> None:
    """Given an unknown or malformed bin id, when exported, then not-found is raised before streaming starts."""
    # Given
    exports = ExportService(database)
    # When / Then
    with pytest.raises(BinNotFoundError):
        await exports.export(bin_id)
