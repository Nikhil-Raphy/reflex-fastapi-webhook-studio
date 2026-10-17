"""Read the app settings from the environment once, and stop on a bad value."""

from dataclasses import dataclass
from functools import cache
from os import environ
from typing import TYPE_CHECKING, Self

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from reflex_fastapi_webhook_studio.domain import BinListing

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

PREFIX = "WEBHOOK_STUDIO_"
DRIVERS = frozenset({"sqlite+aiosqlite", "postgresql+psycopg"})
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class SettingsError(ValueError):
    """A setting in the environment has a bad value."""


@dataclass(slots=True, frozen=True, kw_only=True)
class Settings:
    """The app settings.

    Attributes:
        database_url: Async SQLAlchemy URL of the database.
        cors_enabled: Whether capture replies carry CORS headers.
        max_body_bytes: Largest request body the app stores.
        max_requests_per_bin: Most requests a bin keeps; the oldest go first.
        bin_ttl_days: Days a bin lives after its last captured request.
        max_bins: Most bins the app holds at once.
        bin_listing: Which bins the home page lists.
        log_level: Name of the stdlib log level.
    """

    database_url: str = "sqlite+aiosqlite:///data/webhook_studio.db"
    cors_enabled: bool = True
    max_body_bytes: int = 1_048_576
    max_requests_per_bin: int = 500
    bin_ttl_days: int = 7
    max_bins: int = 1000
    bin_listing: BinListing = BinListing.BROWSER
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Build settings from environment variables, using the default for each one not set.

        Args:
            env: The environment to read.

        Returns:
            The settings.
        """
        defaults = cls()

        def read[T](field: str, parse: Callable[[str, str], T], default: T) -> T:
            name = PREFIX + field.upper()
            return parse(name, env[name]) if name in env else default

        return cls(
            database_url=read("database_url", _database_url, defaults.database_url),
            cors_enabled=read("cors_enabled", _boolean, defaults.cors_enabled),
            max_body_bytes=read("max_body_bytes", _positive_int, defaults.max_body_bytes),
            max_requests_per_bin=read("max_requests_per_bin", _positive_int, defaults.max_requests_per_bin),
            bin_ttl_days=read("bin_ttl_days", _positive_int, defaults.bin_ttl_days),
            max_bins=read("max_bins", _positive_int, defaults.max_bins),
            bin_listing=read("bin_listing", _bin_listing, defaults.bin_listing),
            log_level=read("log_level", _log_level, defaults.log_level),
        )


@cache
def get_settings() -> Settings:
    """Read the settings from the process environment the first time, then reuse them.

    Returns:
        The settings.
    """
    return Settings.from_env(environ)


def _positive_int(name: str, raw: str) -> int:
    if not raw.strip().isdigit() or int(raw) < 1:
        msg = f"{name} must be a whole number of at least 1, not {raw!r}."
        raise SettingsError(msg)
    return int(raw)


def _boolean(name: str, raw: str) -> bool:
    match raw.strip().lower():
        case "true":
            return True
        case "false":
            return False
        case _:
            msg = f"{name} must be true or false, not {raw!r}."
            raise SettingsError(msg)


def _bin_listing(name: str, raw: str) -> BinListing:
    try:
        return BinListing(raw.strip().lower())
    except ValueError:
        msg = f"{name} must be one of {', '.join(BinListing)}, not {raw!r}."
        raise SettingsError(msg) from None


def _log_level(name: str, raw: str) -> str:
    level = raw.strip().upper()
    if level not in LOG_LEVELS:
        msg = f"{name} must be one of {', '.join(sorted(LOG_LEVELS))}, not {raw!r}."
        raise SettingsError(msg)
    return level


def _database_url(name: str, raw: str) -> str:
    try:
        driver = make_url(raw).drivername
    except ArgumentError as error:
        # The URL may hold a password, so the message leaves it out.
        msg = f"{name} is not a database URL."
        raise SettingsError(msg) from error
    if driver not in DRIVERS:
        msg = f"{name} must use one of {', '.join(sorted(DRIVERS))}, not {driver!r}."
        raise SettingsError(msg)
    return raw
