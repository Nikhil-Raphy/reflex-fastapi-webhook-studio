"""Tests for the database queries, on SQLite and PostgreSQL."""

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid7

import pytest

from reflex_fastapi_webhook_studio.db import repository
from reflex_fastapi_webhook_studio.domain import HttpMethod, ReplyConfig, RequestFilter
from tests.factories import NOW, make_bin, make_request

if TYPE_CHECKING:
    from uuid import UUID

    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.domain import Bin, CapturedRequest


@pytest.mark.anyio
async def test_given_new_bin_when_stored_and_read_then_it_comes_back_unchanged(database: Database) -> None:
    """Given a new bin, when it is stored and read back, then every field, time zone included, is the same."""
    # Given
    bin_ = make_bin()
    async with database.sessions.begin() as session:
        await repository.add_bin(session, bin_)
    # When
    async with database.sessions() as session:
        stored = await repository.get_bin(session, bin_.id)
        count = await repository.count_bins(session)
    # Then
    assert stored == bin_
    assert count == 1


@pytest.mark.anyio
async def test_given_unknown_id_when_bin_is_read_then_nothing_is_found(database: Database) -> None:
    """Given no bin with an id, when that id is read, then nothing comes back."""
    # Given
    bin_id = make_bin().id
    # When
    async with database.sessions() as session:
        stored = await repository.get_bin(session, bin_id)
    # Then
    assert stored is None


@pytest.mark.anyio
async def test_given_bin_when_label_is_set_then_the_new_label_is_stored(database: Database) -> None:
    """Given a bin, when its label is set, then the bin comes back with the new label."""
    # Given
    bin_ = make_bin(label="old")
    async with database.sessions.begin() as session:
        await repository.add_bin(session, bin_)
    # When
    async with database.sessions.begin() as session:
        updated = await repository.set_label(session, bin_.id, "new")
    # Then
    assert updated is not None
    assert updated.label == "new"


@pytest.mark.anyio
async def test_given_unknown_id_when_label_is_set_then_nothing_is_found(database: Database) -> None:
    """Given no bin with an id, when its label is set, then nothing comes back."""
    # Given
    bin_id = make_bin().id
    # When
    async with database.sessions.begin() as session:
        updated = await repository.set_label(session, bin_id, "new")
    # Then
    assert updated is None


@pytest.mark.anyio
async def test_given_bin_when_touched_then_activity_and_expiry_move(database: Database) -> None:
    """Given a bin, when it is touched, then its last activity and expiry take the new times."""
    # Given
    bin_ = make_bin()
    later, expires = NOW + timedelta(hours=1), NOW + timedelta(days=8)
    async with database.sessions.begin() as session:
        await repository.add_bin(session, bin_)
    # When
    async with database.sessions.begin() as session:
        await repository.touch_bin(session, bin_.id, at=later, expires_at=expires)
    # Then
    async with database.sessions() as session:
        stored = await repository.get_bin(session, bin_.id)
    assert stored is not None
    assert (stored.last_activity_at, stored.expires_at) == (later, expires)


@pytest.mark.anyio
async def test_given_request_when_stored_and_read_then_bytes_and_header_order_are_kept(database: Database) -> None:
    """Given a captured request, when it is stored and read back, then body bytes and header order are the same."""
    # Given
    bin_ = make_bin()
    request = make_request(bin_.id, body=b"\x00\xff raw bytes")
    async with database.sessions.begin() as session:
        await repository.add_bin(session, bin_)
        await repository.add_request(session, request)
    # When
    async with database.sessions() as session:
        stored = await repository.get_request(session, bin_.id, request.id)
    # Then
    assert stored == request


@pytest.mark.anyio
async def test_given_request_in_other_bin_when_read_then_nothing_is_found(database: Database) -> None:
    """Given a request in one bin, when it is read through another bin, then nothing comes back."""
    # Given
    first, second = make_bin(), make_bin()
    request = make_request(first.id)
    async with database.sessions.begin() as session:
        await repository.add_bin(session, first)
        await repository.add_bin(session, second)
        await repository.add_request(session, request)
    # When
    async with database.sessions() as session:
        stored = await repository.get_request(session, second.id, request.id)
        missing = await repository.get_request(session, first.id, uuid7())
    # Then
    assert stored is None
    assert missing is None


@pytest.mark.anyio
async def test_given_requests_when_listed_then_newest_come_first_up_to_limit(database: Database) -> None:
    """Given four requests, when two are listed, then the two newest come back, newest first."""
    # Given
    bin_ = make_bin()
    requests = [make_request(bin_.id, at=NOW + timedelta(seconds=n)) for n in range(4)]
    async with database.sessions.begin() as session:
        await repository.add_bin(session, bin_)
        for request in requests:
            await repository.add_request(session, request)
    # When
    async with database.sessions() as session:
        rows = await repository.list_requests(session, bin_.id, limit=2)
    # Then
    assert [row.id for row in rows] == [requests[3].id, requests[2].id]
    assert rows[0].body_size == requests[3].body_size


@pytest.mark.anyio
async def test_given_more_requests_than_cap_when_trimmed_then_only_newest_remain(database: Database) -> None:
    """Given five requests, when the bin is trimmed to three, then only the three newest remain."""
    # Given
    bin_ = make_bin()
    requests = [make_request(bin_.id) for _ in range(5)]
    async with database.sessions.begin() as session:
        await repository.add_bin(session, bin_)
        for request in requests:
            await repository.add_request(session, request)
    # When
    async with database.sessions.begin() as session:
        await repository.trim_requests(session, bin_.id, keep=3)
    # Then
    async with database.sessions() as session:
        rows = await repository.list_requests(session, bin_.id, limit=10)
    assert [row.id for row in rows] == [request.id for request in reversed(requests[2:])]


@pytest.mark.anyio
async def test_given_fewer_requests_than_cap_when_trimmed_then_all_remain(database: Database) -> None:
    """Given two requests, when the bin is trimmed to three, then both remain."""
    # Given
    bin_ = make_bin()
    requests = [make_request(bin_.id) for _ in range(2)]
    async with database.sessions.begin() as session:
        await repository.add_bin(session, bin_)
        for request in requests:
            await repository.add_request(session, request)
    # When
    async with database.sessions.begin() as session:
        await repository.trim_requests(session, bin_.id, keep=3)
    # Then
    async with database.sessions() as session:
        rows = await repository.list_requests(session, bin_.id, limit=10)
    assert len(rows) == 2


async def stored_bin_with(database: Database, *requests: CapturedRequest, bin_: Bin | None = None) -> Bin:
    """Store a bin and some requests in it.

    Args:
        database: The test database.
        *requests: The requests, already pointing at the bin.
        bin_: The bin; a new one when None.

    Returns:
        The stored bin.
    """
    bin_ = bin_ or make_bin()
    async with database.sessions.begin() as session:
        await repository.add_bin(session, bin_)
        for request in requests:
            await repository.add_request(session, request)
    return bin_


@pytest.mark.anyio
async def test_given_mixed_requests_when_filtered_then_method_and_text_match_in_any_case(database: Database) -> None:
    """Given requests with different methods, paths, headers and bodies, when filtered, then only matches return."""
    # Given
    bin_ = make_bin()
    get = replace(make_request(bin_.id, body=b""), method=HttpMethod.GET, path="/Orders", query_string="")
    invoice = make_request(bin_.id, body=b'{"kind": "INVOICE"}')
    header = replace(make_request(bin_.id), headers=(("x-event", "Refund.created"),))
    percent = replace(make_request(bin_.id, body=b"100% done"), path="/p")
    await stored_bin_with(database, get, invoice, header, percent, bin_=bin_)

    async def ids(where: RequestFilter) -> list[UUID]:
        async with database.sessions() as session:
            rows = await repository.list_requests(session, bin_.id, limit=10, where=where)
            assert await repository.count_requests(session, bin_.id, where) == len(rows)
        return [row.id for row in rows]

    # When
    by_method = await ids(RequestFilter(method=HttpMethod.GET))
    by_body = await ids(RequestFilter(text="invoice"))
    by_path = await ids(RequestFilter(text="orders"))
    by_header = await ids(RequestFilter(text="refund.CREATED"))
    by_both = await ids(RequestFilter(method=HttpMethod.GET, text="invoice"))
    wildcard = await ids(RequestFilter(text="0%"))
    no_match = await ids(RequestFilter(text="%_"))
    # Then
    assert (by_method, by_body, by_path, by_header) == ([get.id], [invoice.id], [get.id], [header.id])
    assert (by_both, wildcard, no_match) == ([], [percent.id], [])


@pytest.mark.anyio
async def test_given_many_requests_when_paged_with_before_then_pages_follow_without_gaps(database: Database) -> None:
    """Given five requests, when read two at a time with the before cursor, then the pages follow, newest first."""
    # Given
    bin_ = make_bin()
    requests = [make_request(bin_.id, at=NOW + timedelta(seconds=n)) for n in range(5)]
    await stored_bin_with(database, *requests, bin_=bin_)
    pages: list[list[UUID]] = []
    before = None
    # When
    async with database.sessions() as session:
        while True:
            rows = await repository.list_requests(session, bin_.id, limit=2, before=before)
            if not rows:
                break
            pages.append([row.id for row in rows])
            before = rows[-1].id
    # Then
    assert pages == [[requests[4].id, requests[3].id], [requests[2].id, requests[1].id], [requests[0].id]]


@pytest.mark.anyio
async def test_given_requests_when_read_after_a_cursor_then_they_come_oldest_first_in_full(database: Database) -> None:
    """Given three requests, when read in full after the first, then the other two come back oldest first."""
    # Given
    bin_ = make_bin()
    requests = [make_request(bin_.id, at=NOW + timedelta(seconds=n)) for n in range(3)]
    await stored_bin_with(database, *requests, bin_=bin_)
    # When
    async with database.sessions() as session:
        everything = await repository.requests_after(session, bin_.id, after=None, limit=10)
        later = await repository.requests_after(session, bin_.id, after=requests[0].id, limit=10)
    # Then
    assert everything == requests
    assert later == requests[1:]


@pytest.mark.anyio
async def test_given_requests_when_one_is_deleted_or_the_bin_cleared_then_they_are_gone(database: Database) -> None:
    """Given three requests, when one is deleted and then the bin cleared, then the bin holds none and stays."""
    # Given
    bin_ = make_bin()
    requests = [make_request(bin_.id) for _ in range(3)]
    other = make_bin()
    await stored_bin_with(database, *requests, bin_=bin_)
    await stored_bin_with(database, make_request(other.id), bin_=other)
    # When
    async with database.sessions.begin() as session:
        deleted = await repository.delete_request(session, bin_.id, requests[0].id)
        again = await repository.delete_request(session, bin_.id, requests[0].id)
        wrong_bin = await repository.delete_request(session, other.id, requests[1].id)
    async with database.sessions.begin() as session:
        await repository.clear_requests(session, bin_.id)
    # Then
    async with database.sessions() as session:
        assert await repository.count_requests(session, bin_.id) == 0
        assert await repository.count_requests(session, other.id) == 1
        assert await repository.get_bin(session, bin_.id) is not None
    assert (deleted, again, wrong_bin) == (True, False, False)


@pytest.mark.anyio
async def test_given_bin_with_requests_when_deleted_then_its_requests_go_too(database: Database) -> None:
    """Given a bin with a request, when the bin is deleted, then the database deletes the request with it."""
    # Given
    bin_ = make_bin()
    request = make_request(bin_.id)
    await stored_bin_with(database, request, bin_=bin_)
    # When
    async with database.sessions.begin() as session:
        deleted = await repository.delete_bin(session, bin_.id)
        again = await repository.delete_bin(session, bin_.id)
    # Then
    async with database.sessions() as session:
        assert await repository.get_request(session, bin_.id, request.id) is None
        assert await repository.count_requests(session, bin_.id) == 0
    assert (deleted, again) == (True, False)


@pytest.mark.anyio
async def test_given_expired_and_live_bins_when_swept_then_only_expired_ones_go(database: Database) -> None:
    """Given a bin past its expiry and one before it, when expired bins are deleted, then only the first goes."""
    # Given
    expired = make_bin(at=NOW - timedelta(days=8))
    live = make_bin(at=NOW - timedelta(days=6))
    await stored_bin_with(database, make_request(expired.id), bin_=expired)
    await stored_bin_with(database, bin_=live)
    # When
    async with database.sessions.begin() as session:
        deleted = await repository.delete_expired_bins(session, NOW)
    # Then
    async with database.sessions() as session:
        left = await repository.list_bins(session)
    assert deleted == [expired.id]
    assert [row.id for row in left] == [live.id]
    assert left[0].expires_at == live.expires_at


@pytest.mark.anyio
async def test_given_bin_when_reply_is_set_then_it_is_stored_and_read_back(database: Database) -> None:
    """Given a bin, when its reply settings are set, then the bin reads back with them; an unknown bin gives None."""
    # Given
    bin_ = await stored_bin_with(database)
    reply = ReplyConfig(status=418, content_type="text/plain", headers=(("X-Tea", "yes"),), body="", delay_ms=5)
    # When
    async with database.sessions.begin() as session:
        updated = await repository.set_reply(session, bin_.id, reply)
        missing = await repository.set_reply(session, make_bin().id, reply)
    async with database.sessions() as session:
        stored = await repository.get_bin(session, bin_.id)
    # Then
    assert updated == stored == replace(bin_, reply=reply)
    assert missing is None
