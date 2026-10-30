"""Tests for the security controls in the design: access, injection, CORS and logs."""

import logging
from typing import TYPE_CHECKING, override

import pytest

from reflex_fastapi_webhook_studio.domain import BIN_ID_LENGTH, new_bin_id
from reflex_fastapi_webhook_studio.log_config import LOGGER_NAME
from tests.factories import api_client

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.db.engine import Database

SECRET_BODY = b'{"card": "4111-secret-body"}'
SECRET_TOKEN = "Bearer secret-token-value"  # noqa: S105  # A fake value the test looks for in logs.


class Collector(logging.Handler):
    """Keeps every log record it gets."""

    def __init__(self) -> None:
        """Start with no records."""
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Keep the record.

        Args:
            record: The log record.
        """
        self.records.append(record)


def test_given_new_bin_ids_when_made_then_each_is_22_url_safe_characters_and_unique() -> None:
    """Given many new bin ids, when made, then each holds 22 URL-safe characters and none repeat."""
    # Given
    count = 1000
    # When
    ids = {new_bin_id() for _ in range(count)}
    # Then
    assert len(ids) == count
    assert all(len(bin_id) == BIN_ID_LENGTH and bin_id.replace("-", "").replace("_", "").isalnum() for bin_id in ids)


@pytest.mark.anyio
async def test_given_request_in_one_bin_when_reached_through_another_then_404_everywhere(database: Database) -> None:
    """Given a request in bin A, when read, deleted, copied or replayed through bin B, then every reply is 404."""
    # Given
    async with api_client(database) as client:
        owner = (await client.post("/api/v1/bins")).json()["id"]
        other = (await client.post("/api/v1/bins")).json()["id"]
        request_id = (await client.post(f"/api/webhook/{owner}", content=b"x")).json()["request_id"]
        base = f"/api/v1/bins/{other}/requests/{request_id}"
        # When
        replies = [
            await client.get(base),
            await client.get(f"{base}/curl"),
            await client.post(f"{base}/replay", json={"target_url": "https://example.com"}),
            await client.delete(base),
        ]
        still_there = await client.get(f"/api/v1/bins/{owner}/requests/{request_id}")
    # Then
    assert [reply.status_code for reply in replies] == [404, 404, 404, 404]
    assert still_there.status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["'; DROP TABLE captured_request; --", '" OR 1=1 --', "\\", "%' OR '1'='1"])
async def test_given_sql_in_search_when_listed_then_it_is_only_text(database: Database, text: str) -> None:
    """Given SQL in the search text, when requests are listed, then nothing matches and the table is intact."""
    # Given
    async with api_client(database) as client:
        bin_id = (await client.post("/api/v1/bins")).json()["id"]
        await client.post(f"/api/webhook/{bin_id}", content=b"plain")
        # When
        found = await client.get(f"/api/v1/bins/{bin_id}/requests", params={"q": text})
        everything = await client.get(f"/api/v1/bins/{bin_id}/requests")
    # Then
    assert (found.status_code, found.json()) == (200, [])
    assert len(everything.json()) == 1


@pytest.mark.anyio
async def test_given_browser_origin_when_management_api_is_called_then_no_cors_headers(database: Database) -> None:
    """Given a request from another site's origin, when it calls /api/v1, then no reply grants that site access."""
    # Given
    origin = {"origin": "https://evil.example"}
    async with api_client(database) as client:
        # When
        created = await client.post("/api/v1/bins", headers=origin)
        preflight = await client.options("/api/v1/bins", headers={**origin, "access-control-request-method": "POST"})
    # Then
    for reply in (created, preflight):
        assert not any(name.startswith("access-control-") for name in reply.headers)


@pytest.mark.anyio
async def test_given_secret_body_and_header_when_captured_and_replayed_then_logs_hold_neither(
    database: Database,
) -> None:
    """Given a body and an Authorization header, when captured, read and replayed, then no app log holds them."""
    # Given
    collector = Collector()
    app_logger = logging.getLogger(LOGGER_NAME)
    app_logger.addHandler(collector)
    level = app_logger.level
    app_logger.setLevel(logging.DEBUG)
    try:
        async with api_client(database) as client:
            bin_id = (await client.post("/api/v1/bins")).json()["id"]
            # When
            sent = await client.post(
                f"/api/webhook/{bin_id}", content=SECRET_BODY, headers={"authorization": SECRET_TOKEN}
            )
            request_id = sent.json()["request_id"]
            await client.get(f"/api/v1/bins/{bin_id}/requests/{request_id}")
            await client.post(
                f"/api/v1/bins/{bin_id}/requests/{request_id}/replay", json={"target_url": "http://127.0.0.1:9/"}
            )
            await client.delete(f"/api/v1/bins/{bin_id}")
    finally:
        app_logger.removeHandler(collector)
        app_logger.setLevel(level)
    # Then
    text = "\n".join(record.getMessage() for record in collector.records)
    assert collector.records
    assert "secret-body" not in text
    assert "secret-token" not in text
    assert bin_id not in text
    assert bin_id[:6] in text
