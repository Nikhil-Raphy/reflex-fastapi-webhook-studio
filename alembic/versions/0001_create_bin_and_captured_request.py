"""Create the bin and captured_request tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

# Alembic needs these file and variable names.
# pylint: disable=invalid-name

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    """Create both tables and their indexes."""
    op.create_table(
        "bin",
        sa.Column("id", sa.String(22), primary_key=True),
        sa.Column("label", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reply_status", sa.Integer(), nullable=False, server_default=sa.text("200")),
        sa.Column("reply_content_type", sa.String(255), nullable=True),
        sa.Column("reply_headers", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("reply_body", sa.Text(), nullable=True),
        sa.Column("reply_delay_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_bin_expires_at", "bin", ["expires_at"])
    op.create_table(
        "captured_request",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("bin_id", sa.String(22), sa.ForeignKey("bin.id", ondelete="CASCADE"), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(7), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("query_string", sa.Text(), nullable=False),
        sa.Column("query_params", JSON_TYPE, nullable=False),
        sa.Column("headers", JSON_TYPE, nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("body_size", sa.Integer(), nullable=False),
        sa.Column("body_truncated", sa.Boolean(), nullable=False),
        sa.Column("body_preview", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("remote_addr", sa.String(45), nullable=True),
        sa.Column("http_version", sa.String(8), nullable=False),
        sa.Column("reply_status", sa.Integer(), nullable=False),
    )
    op.create_index("ix_captured_request_bin_id_id", "captured_request", ["bin_id", sa.text("id DESC")])


def downgrade() -> None:
    """Drop both tables."""
    op.drop_index("ix_captured_request_bin_id_id", table_name="captured_request")
    op.drop_table("captured_request")
    op.drop_index("ix_bin_expires_at", table_name="bin")
    op.drop_table("bin")
