"""Stdlib logging that writes one JSON object per line.

Never pass request bodies or header values to a logger, and pass bin ids through `short_id`.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import override

LOGGER_NAME = "reflex_fastapi_webhook_studio"
SHORT_ID_LENGTH = 6


class JsonFormatter(logging.Formatter):
    """Format a log record as a single JSON object."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Format the record.

        Args:
            record: The log record.

        Returns:
            The record as one line of JSON.
        """
        data = {
            "time": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Send the app's logs to stderr as JSON, at the given level.

    Only the app's own logger changes; Reflex and other libraries keep their logging.

    Args:
        level: Name of the stdlib log level.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False


def short_id(bin_id: str) -> str:
    """Shorten a bin id for logs, since the full id is the secret that guards the bin.

    Args:
        bin_id: The full bin id.

    Returns:
        The first six characters.
    """
    return bin_id[:SHORT_ID_LENGTH]
