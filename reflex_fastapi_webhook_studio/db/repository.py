"""Queries for bins and captured requests; they take and return domain values, never rows."""

from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, Select, Text, cast, delete, func, or_, select, update
from sqlmodel import col

from reflex_fastapi_webhook_studio.db.models import BinRow, CapturedRequestRow
from reflex_fastapi_webhook_studio.domain import (
    EVERY_REQUEST,
    Bin,
    BinSummary,
    CapturedRequest,
    HttpMethod,
    NameValuePairs,
    ReplyConfig,
    RequestFilter,
    RequestSummary,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def add_bin(session: AsyncSession, bin_: Bin) -> None:
    """Store a new bin.

    Args:
        session: An open session; the caller commits.
        bin_: The bin.
    """
    session.add(
        BinRow(
            id=bin_.id,
            label=bin_.label,
            created_at=bin_.created_at,
            last_activity_at=bin_.last_activity_at,
            expires_at=bin_.expires_at,
            reply_status=bin_.reply.status,
            reply_content_type=bin_.reply.content_type,
            reply_headers=[list(pair) for pair in bin_.reply.headers],
            reply_body=bin_.reply.body,
            reply_delay_ms=bin_.reply.delay_ms,
        )
    )
    await session.flush()


async def count_bins(session: AsyncSession) -> int:
    """Count the stored bins.

    Args:
        session: An open session.

    Returns:
        The number of bins.
    """
    return (await session.execute(select(func.count()).select_from(BinRow))).scalar_one()


async def get_bin(session: AsyncSession, bin_id: str) -> Bin | None:
    """Read one bin.

    Args:
        session: An open session.
        bin_id: The bin id.

    Returns:
        The bin, or None if no bin has that id.
    """
    row = await session.get(BinRow, bin_id)
    return None if row is None else _bin(row)


async def list_bins(session: AsyncSession, bin_ids: Collection[str] | None = None) -> list[BinSummary]:
    """List bins with their request counts, the most recently active first.

    Args:
        session: An open session.
        bin_ids: The bins to list; every bin when None.

    Returns:
        Short forms of the bins.
    """
    query = _bin_summaries()
    if bin_ids is not None:
        query = query.where(col(BinRow.id).in_(bin_ids))
    rows = await session.execute(query)
    return [
        BinSummary(
            id=row.id,
            label=row.label,
            created_at=row.created_at,
            last_activity_at=row.last_activity_at,
            expires_at=row.expires_at,
            request_count=row.request_count,
        )
        for row in rows
    ]


async def set_label(session: AsyncSession, bin_id: str, label: str | None) -> Bin | None:
    """Change the label of a bin.

    Args:
        session: An open session; the caller commits.
        bin_id: The bin id.
        label: The new label, or None to clear it.

    Returns:
        The changed bin, or None if no bin has that id.
    """
    row = await session.get(BinRow, bin_id)
    if row is None:
        return None
    row.label = label
    await session.flush()
    return _bin(row)


async def set_reply(session: AsyncSession, bin_id: str, reply: ReplyConfig) -> Bin | None:
    """Change what a bin sends back to senders.

    Args:
        session: An open session; the caller commits.
        bin_id: The bin id.
        reply: The new reply settings.

    Returns:
        The changed bin, or None if no bin has that id.
    """
    row = await session.get(BinRow, bin_id)
    if row is None:
        return None
    row.reply_status = reply.status
    row.reply_content_type = reply.content_type
    row.reply_headers = [list(pair) for pair in reply.headers]
    row.reply_body = reply.body
    row.reply_delay_ms = reply.delay_ms
    await session.flush()
    return _bin(row)


async def touch_bin(session: AsyncSession, bin_id: str, *, at: datetime, expires_at: datetime) -> None:
    """Record activity on a bin and push its expiry out.

    Args:
        session: An open session; the caller commits.
        bin_id: The bin id.
        at: When the activity happened.
        expires_at: The new expiry time.
    """
    await session.execute(
        update(BinRow).where(col(BinRow.id) == bin_id).values(last_activity_at=at, expires_at=expires_at)
    )


async def delete_bin(session: AsyncSession, bin_id: str) -> bool:
    """Delete a bin; the database deletes its requests with it.

    Args:
        session: An open session; the caller commits.
        bin_id: The bin id.

    Returns:
        Whether a bin had that id.
    """
    deleted = await session.execute(delete(BinRow).where(col(BinRow.id) == bin_id).returning(col(BinRow.id)))
    return deleted.scalar_one_or_none() is not None


async def delete_expired_bins(session: AsyncSession, now: datetime) -> list[str]:
    """Delete every bin whose expiry has passed, with its requests.

    Args:
        session: An open session; the caller commits.
        now: The current time.

    Returns:
        The ids of the deleted bins.
    """
    deleted = await session.execute(delete(BinRow).where(col(BinRow.expires_at) <= now).returning(col(BinRow.id)))
    return list(deleted.scalars())


async def add_request(session: AsyncSession, request: CapturedRequest) -> None:
    """Store a captured request.

    Args:
        session: An open session; the caller commits.
        request: The request.
    """
    session.add(
        CapturedRequestRow(
            id=request.id,
            bin_id=request.bin_id,
            received_at=request.received_at,
            method=request.method.value,
            path=request.path,
            query_string=request.query_string,
            query_params=[list(pair) for pair in request.query_params],
            headers=[list(pair) for pair in request.headers],
            body=request.body,
            body_size=request.body_size,
            body_truncated=request.body_truncated,
            body_preview=request.body_preview,
            content_type=request.content_type,
            remote_addr=request.remote_addr,
            http_version=request.http_version,
            reply_status=request.reply_status,
        )
    )
    await session.flush()


async def trim_requests(session: AsyncSession, bin_id: str, *, keep: int) -> None:
    """Delete all but the newest requests of a bin.

    Args:
        session: An open session; the caller commits.
        bin_id: The bin id.
        keep: How many of the newest requests to keep.
    """
    request_id = col(CapturedRequestRow.id)
    oldest_kept = (
        select(request_id)
        .where(col(CapturedRequestRow.bin_id) == bin_id)
        .order_by(request_id.desc())
        .limit(1)
        .offset(keep - 1)
        .scalar_subquery()
    )
    await session.execute(
        delete(CapturedRequestRow).where(col(CapturedRequestRow.bin_id) == bin_id, request_id < oldest_kept)
    )


async def list_requests(
    session: AsyncSession,
    bin_id: str,
    *,
    limit: int,
    where: RequestFilter = EVERY_REQUEST,
    before: UUID | None = None,
) -> list[RequestSummary]:
    """List a bin's requests that match a filter, newest first.

    Args:
        session: An open session.
        bin_id: The bin id.
        limit: The most requests to return.
        where: Which requests to list.
        before: Only requests older than the one with this id, to read the next page.

    Returns:
        Short forms of the requests.
    """
    query = select(
        col(CapturedRequestRow.id),
        col(CapturedRequestRow.received_at),
        col(CapturedRequestRow.method),
        col(CapturedRequestRow.path),
        col(CapturedRequestRow.query_string),
        col(CapturedRequestRow.body_size),
        col(CapturedRequestRow.body_truncated),
        col(CapturedRequestRow.content_type),
        col(CapturedRequestRow.reply_status),
    ).where(*_matching(bin_id, where))
    if before is not None:
        query = query.where(col(CapturedRequestRow.id) < before)
    rows = await session.execute(query.order_by(col(CapturedRequestRow.id).desc()).limit(limit))
    return [
        RequestSummary(
            id=row.id,
            received_at=row.received_at,
            method=HttpMethod(row.method),
            path=row.path,
            query_string=row.query_string,
            body_size=row.body_size,
            body_truncated=row.body_truncated,
            content_type=row.content_type,
            reply_status=row.reply_status,
        )
        for row in rows
    ]


async def count_requests(session: AsyncSession, bin_id: str, where: RequestFilter = EVERY_REQUEST) -> int:
    """Count a bin's requests that match a filter.

    Args:
        session: An open session.
        bin_id: The bin id.
        where: Which requests to count.

    Returns:
        The number of requests.
    """
    query = select(func.count()).select_from(CapturedRequestRow).where(*_matching(bin_id, where))
    return (await session.execute(query)).scalar_one()


async def requests_after(
    session: AsyncSession, bin_id: str, *, after: UUID | None, limit: int
) -> list[CapturedRequest]:
    """Read a bin's requests in full, oldest first, a page at a time.

    Args:
        session: An open session.
        bin_id: The bin id.
        after: Only requests newer than the one with this id; from the oldest when None.
        limit: The most requests to return.

    Returns:
        The requests.
    """
    query = select(CapturedRequestRow).where(col(CapturedRequestRow.bin_id) == bin_id)
    if after is not None:
        query = query.where(col(CapturedRequestRow.id) > after)
    rows = await session.scalars(query.order_by(col(CapturedRequestRow.id)).limit(limit))
    return [_request(row) for row in rows]


async def get_request(session: AsyncSession, bin_id: str, request_id: UUID) -> CapturedRequest | None:
    """Read one request of a bin.

    Args:
        session: An open session.
        bin_id: The bin id.
        request_id: The request id.

    Returns:
        The request, or None if the bin holds no request with that id.
    """
    row = await session.get(CapturedRequestRow, request_id)
    if row is None or row.bin_id != bin_id:
        return None
    return _request(row)


async def delete_request(session: AsyncSession, bin_id: str, request_id: UUID) -> bool:
    """Delete one request of a bin.

    Args:
        session: An open session; the caller commits.
        bin_id: The bin id.
        request_id: The request id.

    Returns:
        Whether the bin held a request with that id.
    """
    deleted = await session.execute(
        delete(CapturedRequestRow)
        .where(col(CapturedRequestRow.bin_id) == bin_id, col(CapturedRequestRow.id) == request_id)
        .returning(col(CapturedRequestRow.id))
    )
    return deleted.scalar_one_or_none() is not None


async def clear_requests(session: AsyncSession, bin_id: str) -> None:
    """Delete every request of a bin.

    Args:
        session: An open session; the caller commits.
        bin_id: The bin id.
    """
    await session.execute(delete(CapturedRequestRow).where(col(CapturedRequestRow.bin_id) == bin_id))


def _matching(bin_id: str, where: RequestFilter) -> list[ColumnElement[bool]]:
    conditions = [col(CapturedRequestRow.bin_id) == bin_id]
    if where.method is not None:
        conditions.append(col(CapturedRequestRow.method) == where.method.value)
    if where.text:
        conditions.append(
            or_(
                *(
                    column.icontains(where.text, autoescape=True)
                    for column in (
                        col(CapturedRequestRow.method),
                        col(CapturedRequestRow.path),
                        col(CapturedRequestRow.query_string),
                        cast(col(CapturedRequestRow.headers), Text),
                        col(CapturedRequestRow.body_preview),
                    )
                )
            )
        )
    return conditions


def _request(row: CapturedRequestRow) -> CapturedRequest:
    return CapturedRequest(
        id=row.id,
        bin_id=row.bin_id,
        received_at=row.received_at,
        method=HttpMethod(row.method),
        path=row.path,
        query_string=row.query_string,
        query_params=_pairs(row.query_params),
        headers=_pairs(row.headers),
        body=row.body,
        body_size=row.body_size,
        body_truncated=row.body_truncated,
        body_preview=row.body_preview,
        content_type=row.content_type,
        remote_addr=row.remote_addr,
        http_version=row.http_version,
        reply_status=row.reply_status,
    )


def _bin(row: BinRow) -> Bin:
    return Bin(
        id=row.id,
        label=row.label,
        created_at=row.created_at,
        last_activity_at=row.last_activity_at,
        expires_at=row.expires_at,
        reply=ReplyConfig(
            status=row.reply_status,
            content_type=row.reply_content_type,
            headers=_pairs(row.reply_headers),
            body=row.reply_body,
            delay_ms=row.reply_delay_ms,
        ),
    )


def _bin_summaries() -> Select[tuple[str, str | None, datetime, datetime, datetime, int]]:
    request_count = (
        select(func.count())
        .select_from(CapturedRequestRow)
        .where(col(CapturedRequestRow.bin_id) == col(BinRow.id))
        .correlate(BinRow)
        .scalar_subquery()
    )
    return select(
        col(BinRow.id),
        col(BinRow.label),
        col(BinRow.created_at),
        col(BinRow.last_activity_at),
        col(BinRow.expires_at),
        request_count.label("request_count"),
    ).order_by(col(BinRow.last_activity_at).desc(), col(BinRow.id))


def _pairs(stored: list[list[str]]) -> NameValuePairs:
    return tuple((name, value) for name, value in stored)
