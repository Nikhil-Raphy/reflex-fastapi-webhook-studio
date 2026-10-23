"""Tests for the database queries, on SQLite and PostgreSQL."""

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid7

import pytest

from reflex_fastapi_webhook_studio.db import repository
from tests.factories import NOW, make_bin, make_request

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.db.engine import Database


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
