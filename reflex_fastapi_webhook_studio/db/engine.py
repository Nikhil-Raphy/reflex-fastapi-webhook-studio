"""Async engine and sessions for SQLite or PostgreSQL."""

from collections.abc import AsyncIterator  # noqa: TC003  # Reflex reads lifespan task signatures at run time.
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",
)


def prepare_sqlite_folder(url: str) -> None:
    """Create the folder that holds a SQLite file, so a fresh checkout can start.

    Args:
        url: The database URL; other databases are left alone.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)


def create_engine(url: str) -> AsyncEngine:
    """Build an async engine, with the SQLite pragmas set on each new connection.

    Args:
        url: The async SQLAlchemy URL.

    Returns:
        The engine.
    """
    engine = create_async_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    return engine


def _set_sqlite_pragmas(dbapi_connection: Any, _record: object) -> None:  # noqa: ANN401
    cursor = dbapi_connection.cursor()
    for pragma in SQLITE_PRAGMAS:
        cursor.execute(pragma)
    cursor.close()


class Database:
    """One engine and its session maker.

    Attributes:
        url: The async SQLAlchemy URL.
        engine: The async engine.
        sessions: Makes sessions that keep loaded values after commit.
    """

    def __init__(self, url: str) -> None:
        """Build the engine; it opens no connection until first used.

        Args:
            url: The async SQLAlchemy URL.
        """
        self.url = url
        self.engine = create_engine(url)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(self.engine, expire_on_commit=False)

    async def check(self) -> None:
        """Run a trivial query to show the database answers."""
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Prepare the database when the server starts and close its connections when it stops.

        Yields:
            Nothing; the server runs while this waits.
        """
        prepare_sqlite_folder(self.url)
        try:
            yield
        finally:
            await self.engine.dispose()
