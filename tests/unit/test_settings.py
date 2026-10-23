"""Tests for reading settings from the environment."""

import pytest

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
