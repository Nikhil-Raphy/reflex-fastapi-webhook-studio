"""Tests for JSON logging."""

import json
import logging

from reflex_fastapi_webhook_studio.log_config import LOGGER_NAME, JsonFormatter, configure_logging, short_id


def test_given_log_record_when_formatted_then_output_is_one_json_object() -> None:
    """Given a log record, when it is formatted, then the output is JSON with time, level, logger and message."""
    # Given
    record = logging.LogRecord("studio.test", logging.WARNING, __file__, 1, "bin %s full", ("abc123",), None)
    # When
    line = JsonFormatter().format(record)
    # Then
    data = json.loads(line)
    assert data["level"] == "WARNING"
    assert data["logger"] == "studio.test"
    assert data["message"] == "bin abc123 full"
    assert data["time"].endswith("Z")
    assert "exception" not in data


def test_given_record_with_exception_when_formatted_then_traceback_is_included() -> None:
    """Given a record that carries an exception, when it is formatted, then the JSON holds the traceback."""
    # Given
    error = RuntimeError("boom")
    record = logging.LogRecord("studio.test", logging.ERROR, __file__, 1, "failed", None, (RuntimeError, error, None))
    # When
    data = json.loads(JsonFormatter().format(record))
    # Then
    assert "RuntimeError: boom" in data["exception"]


def test_given_level_when_logging_is_configured_twice_then_one_json_handler_is_set() -> None:
    """Given a level, when logging is configured twice, then the app logger has that level and one JSON handler."""
    # Given
    logger = logging.getLogger(LOGGER_NAME)
    # When
    configure_logging("DEBUG")
    configure_logging("DEBUG")
    # Then
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0].formatter, JsonFormatter)
    assert logger.propagate is False


def test_given_bin_id_when_shortened_then_only_first_six_characters_remain() -> None:
    """Given a full bin id, when it is shortened for a log, then only its first six characters remain."""
    # Given
    bin_id = "AbCdEfGhIjKlMnOpQrStUv"
    # When
    shown = short_id(bin_id)
    # Then
    assert shown == "AbCdEf"
