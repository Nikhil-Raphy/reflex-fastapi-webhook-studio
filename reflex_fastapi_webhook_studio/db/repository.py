"""Queries for bins and captured requests; they take and return domain values, never rows."""

from typing import TYPE_CHECKING

from sqlalchemy import Select, delete, func, select, update
from sqlmodel import col

from reflex_fastapi_webhook_studio.db.models import BinRow, CapturedRequestRow
from reflex_fastapi_webhook_studio.domain import (
    Bin,
    BinSummary,
    CapturedRequest,
    HttpMethod,
    NameValuePairs,
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


async def list_requests(session: AsyncSession, bin_id: str, *, limit: int) -> list[RequestSummary]:
    """List the newest requests of a bin, newest first.

    Args:
        session: An open session.
        bin_id: The bin id.
        limit: The most requests to return.

    Returns:
        Short forms of the requests.
    """
    rows = await session.execute(
        select(
            col(CapturedRequestRow.id),
            col(CapturedRequestRow.received_at),
            col(CapturedRequestRow.method),
            col(CapturedRequestRow.path),
            col(CapturedRequestRow.query_string),
            col(CapturedRequestRow.body_size),
            col(CapturedRequestRow.body_truncated),
            col(CapturedRequestRow.content_type),
            col(CapturedRequestRow.reply_status),
        )
        .where(col(CapturedRequestRow.bin_id) == bin_id)
        .order_by(col(CapturedRequestRow.id).desc())
        .limit(limit)
    )
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
    )


def _bin_summaries() -> Select[tuple[str, str | None, datetime, datetime, int]]:
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
        request_count.label("request_count"),
    ).order_by(col(BinRow.last_activity_at).desc(), col(BinRow.id))


def _pairs(stored: list[list[str]]) -> NameValuePairs:
    return tuple((name, value) for name, value in stored)
