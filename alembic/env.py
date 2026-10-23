"""Run Alembic migrations against the app database with an async engine."""

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from reflex_fastapi_webhook_studio.db.engine import prepare_sqlite_folder
from reflex_fastapi_webhook_studio.db.models import BinRow
from reflex_fastapi_webhook_studio.settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Every table model shares this metadata.
target_metadata = BinRow.metadata
database_url: str = config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    """Write the migration SQL out instead of running it."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    """Run the migrations on an open connection.

    Args:
        connection: A sync view of the async connection.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect to the database and run the migrations."""
    prepare_sqlite_folder(database_url)
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
