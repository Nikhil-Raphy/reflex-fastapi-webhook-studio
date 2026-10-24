"""Tests for reading settings from the environment."""

import pytest

from reflex_fastapi_webhook_studio.domain import BinListing, ReplayMode
from reflex_fastapi_webhook_studio.settings import Settings, SettingsError


def test_given_no_variables_when_settings_load_then_defaults_apply() -> None:
    """Given an empty environment, when settings load, then every setting has its default."""
    # Given
    env: dict[str, str] = {}
    # When
    settings = Settings.from_env(env)
    # Then
    assert settings == Settings(
        database_url="sqlite+aiosqlite:///data/webhook_studio.db",
        cors_enabled=True,
        max_body_bytes=1_048_576,
        max_requests_per_bin=500,
        bin_ttl_days=7,
        max_bins=1000,
        bin_listing=BinListing.BROWSER,
        max_delay_ms=30_000,
        sweep_interval_s=3600,
        replay_mode=ReplayMode.RESTRICTED,
        replay_timeout_s=15,
        public_base_url="",
        log_level="INFO",
    )


def test_given_every_variable_when_settings_load_then_values_are_read() -> None:
    """Given every variable set, when settings load, then each value comes from the environment."""
    # Given
    env = {
        "WEBHOOK_STUDIO_DATABASE_URL": "postgresql+psycopg://user:pw@db:5432/studio",
        "WEBHOOK_STUDIO_CORS_ENABLED": "FALSE",
        "WEBHOOK_STUDIO_MAX_BODY_BYTES": "2048",
        "WEBHOOK_STUDIO_MAX_REQUESTS_PER_BIN": "10",
        "WEBHOOK_STUDIO_BIN_TTL_DAYS": "2",
        "WEBHOOK_STUDIO_MAX_BINS": "5",
        "WEBHOOK_STUDIO_BIN_LISTING": " ALL ",
        "WEBHOOK_STUDIO_MAX_DELAY_MS": "500",
        "WEBHOOK_STUDIO_SWEEP_INTERVAL_S": "60",
        "WEBHOOK_STUDIO_REPLAY_MODE": "Local",
        "WEBHOOK_STUDIO_REPLAY_TIMEOUT_S": "3",
        "WEBHOOK_STUDIO_PUBLIC_BASE_URL": "https://studio.example.com:8443/",
        "WEBHOOK_STUDIO_LOG_LEVEL": "debug",
    }
    # When
    settings = Settings.from_env(env)
    # Then
    assert settings == Settings(
        database_url="postgresql+psycopg://user:pw@db:5432/studio",
        cors_enabled=False,
        max_body_bytes=2048,
        max_requests_per_bin=10,
        bin_ttl_days=2,
        max_bins=5,
        bin_listing=BinListing.ALL,
        max_delay_ms=500,
        sweep_interval_s=60,
        replay_mode=ReplayMode.LOCAL,
        replay_timeout_s=3,
        public_base_url="https://studio.example.com:8443",
        log_level="DEBUG",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WEBHOOK_STUDIO_MAX_BODY_BYTES", "big"),
        ("WEBHOOK_STUDIO_MAX_BODY_BYTES", "0"),
        ("WEBHOOK_STUDIO_MAX_REQUESTS_PER_BIN", "-1"),
        ("WEBHOOK_STUDIO_BIN_TTL_DAYS", "1.5"),
        ("WEBHOOK_STUDIO_MAX_BINS", ""),
        ("WEBHOOK_STUDIO_CORS_ENABLED", "maybe"),
        ("WEBHOOK_STUDIO_BIN_LISTING", "some"),
        ("WEBHOOK_STUDIO_REPLAY_MODE", "open"),
        ("WEBHOOK_STUDIO_MAX_DELAY_MS", "0"),
        ("WEBHOOK_STUDIO_PUBLIC_BASE_URL", "ftp://studio.example.com"),
        ("WEBHOOK_STUDIO_PUBLIC_BASE_URL", "https://studio.example.com/sub"),
        ("WEBHOOK_STUDIO_PUBLIC_BASE_URL", "https://user:pw@studio.example.com"),
        ("WEBHOOK_STUDIO_PUBLIC_BASE_URL", "https://studio.example.com:99999"),
        ("WEBHOOK_STUDIO_PUBLIC_BASE_URL", "https://"),
        ("WEBHOOK_STUDIO_LOG_LEVEL", "LOUD"),
        ("WEBHOOK_STUDIO_DATABASE_URL", "mysql://db/studio"),
        ("WEBHOOK_STUDIO_DATABASE_URL", "not a url"),
    ],
)
def test_given_bad_value_when_settings_load_then_error_names_variable(name: str, value: str) -> None:
    """Given a bad value in one variable, when settings load, then the error names that variable."""
    # Given
    env = {name: value}
    # When
    with pytest.raises(SettingsError) as caught:
        Settings.from_env(env)
    # Then
    assert name in str(caught.value)


def test_given_blank_public_url_when_settings_load_then_it_stays_unset() -> None:
    """Given a public base URL of spaces, when settings load, then the app uses its own address."""
    # Given
    env = {"WEBHOOK_STUDIO_PUBLIC_BASE_URL": "   "}
    # When
    settings = Settings.from_env(env)
    # Then
    assert not settings.public_base_url
