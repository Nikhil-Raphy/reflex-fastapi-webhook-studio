"""Tables for bins and captured requests."""

from datetime import UTC, datetime
from typing import Any, ClassVar, override
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


# SQLAlchemy's type classes have deep bases, and process_literal_param is optional for decorators.
class UtcDateTime(TypeDecorator[datetime]):  # pylint: disable=abstract-method,too-many-ancestors
    """A datetime stored in UTC and always read back with its time zone."""

    impl = DateTime(timezone=True)
    cache_ok = True

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Convert to UTC before storing; SQLite gets a plain UTC value since it keeps no zone.

        Args:
            value: A datetime with a time zone, or None.
            dialect: The database dialect.

        Returns:
            The value to store.

        Raises:
            ValueError: If the value has no time zone.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            msg = "Store only datetimes that carry a time zone."
            raise ValueError(msg)
        utc = value.astimezone(UTC)
        return utc.replace(tzinfo=None) if dialect.name == "sqlite" else utc

    @override
    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Mark a stored value as UTC when the database dropped the zone.

        Args:
            value: The stored datetime, or None.
            dialect: The database dialect.

        Returns:
            The datetime in UTC.
        """
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class BinRow(SQLModel, table=True):
    """A row in the `bin` table."""

    __tablename__: ClassVar[Any] = "bin"

    id: str = Field(sa_column=Column(String(22), primary_key=True))
    label: str | None = Field(default=None, sa_column=Column(String(80), nullable=True))
    created_at: datetime = Field(sa_column=Column(UtcDateTime(), nullable=False))
    last_activity_at: datetime = Field(sa_column=Column(UtcDateTime(), nullable=False))
    expires_at: datetime = Field(sa_column=Column(UtcDateTime(), nullable=False, index=True))
    reply_status: int = Field(default=200, sa_column=Column(Integer, nullable=False, server_default=text("200")))
    reply_content_type: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    reply_headers: list[list[str]] = Field(
        default_factory=list, sa_column=Column(JSON_TYPE, nullable=False, server_default=text("'[]'"))
    )
    reply_body: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    reply_delay_ms: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))


class CapturedRequestRow(SQLModel, table=True):
    """A row in the `captured_request` table."""

    __tablename__: ClassVar[Any] = "captured_request"
    __table_args__: ClassVar[Any] = (Index("ix_captured_request_bin_id_id", "bin_id", text("id DESC")),)

    id: UUID = Field(sa_column=Column(Uuid, primary_key=True))
    bin_id: str = Field(sa_column=Column(String(22), ForeignKey("bin.id", ondelete="CASCADE"), nullable=False))
    received_at: datetime = Field(sa_column=Column(UtcDateTime(), nullable=False))
    method: str = Field(sa_column=Column(String(7), nullable=False))
    path: str = Field(sa_column=Column(Text, nullable=False))
    query_string: str = Field(sa_column=Column(Text, nullable=False))
    query_params: list[list[str]] = Field(sa_column=Column(JSON_TYPE, nullable=False))
    headers: list[list[str]] = Field(sa_column=Column(JSON_TYPE, nullable=False))
    body: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    body_size: int = Field(sa_column=Column(Integer, nullable=False))
    body_truncated: bool = Field(sa_column=Column(Boolean, nullable=False))
    body_preview: str = Field(sa_column=Column(Text, nullable=False))
    content_type: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    remote_addr: str | None = Field(default=None, sa_column=Column(String(45), nullable=True))
    http_version: str = Field(sa_column=Column(String(8), nullable=False))
    reply_status: int = Field(sa_column=Column(Integer, nullable=False))
