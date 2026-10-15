"""Tests for the bin and request routes under /api/v1."""

import base64
from typing import TYPE_CHECKING
from uuid import uuid7

import pytest

from reflex_fastapi_webhook_studio.settings import Settings
from tests.factories import api_client

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.db.engine import Database


@pytest.mark.anyio
async def test_given_label_when_bin_is_created_then_201_and_it_can_be_read(database: Database) -> None:
    """Given a label, when a bin is created, then the reply is 201 and reading the bin gives the same body."""
    # Given
    async with api_client(database) as client:
        # When
        created = await client.post("/api/v1/bins", json={"label": "orders"})
        read = await client.get(f"/api/v1/bins/{created.json()['id']}")
    # Then
    assert created.status_code == 201
    assert created.json()["label"] == "orders"
    assert len(created.json()["id"]) == 22
    assert read.json() == created.json()


@pytest.mark.anyio
async def test_given_no_body_when_bin_is_created_then_label_is_empty(database: Database) -> None:
    """Given no request body, when a bin is created, then it has no label."""
    # Given
    async with api_client(database) as client:
        # When
        created = await client.post("/api/v1/bins")
    # Then
    assert created.status_code == 201
    assert created.json()["label"] is None


@pytest.mark.anyio
async def test_given_long_label_when_bin_is_created_then_422_problem(database: Database) -> None:
    """Given a label over 80 characters, when a bin is created, then the reply is 422 with a problem body."""
    # Given
    async with api_client(database) as client:
        # When
        response = await client.post("/api/v1/bins", json={"label": "x" * 81})
    # Then
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["errors"]


@pytest.mark.anyio
async def test_given_bin_cap_reached_when_bin_is_created_then_409_problem(database: Database) -> None:
    """Given the app holds the most bins it may, when one more is created, then the reply is 409 with a problem body."""
    # Given
    async with api_client(database, Settings(max_bins=1)) as client:
        await client.post("/api/v1/bins")
        # When
        response = await client.post("/api/v1/bins")
    # Then
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.anyio
async def test_given_bin_when_label_is_patched_then_new_label_is_returned(database: Database) -> None:
    """Given a bin, when its label is patched, then the reply holds the new label."""
    # Given
    async with api_client(database) as client:
        bin_id = (await client.post("/api/v1/bins", json={"label": "old"})).json()["id"]
        # When
        response = await client.patch(f"/api/v1/bins/{bin_id}", json={"label": "new"})
    # Then
    assert response.status_code == 200
    assert response.json()["label"] == "new"


@pytest.mark.anyio
@pytest.mark.parametrize("bin_id", ["AbCdEfGhIjKlMnOpQrStUv", "bad"])
async def test_given_unknown_bin_when_read_or_patched_then_404_problem(database: Database, bin_id: str) -> None:
    """Given an unknown or malformed bin id, when the bin is read, patched or listed, then each reply is 404."""
    # Given
    async with api_client(database) as client:
        # When
        replies = [
            await client.get(f"/api/v1/bins/{bin_id}"),
            await client.patch(f"/api/v1/bins/{bin_id}", json={"label": "x"}),
            await client.get(f"/api/v1/bins/{bin_id}/requests"),
        ]
    # Then
    assert [reply.status_code for reply in replies] == [404, 404, 404]
    assert {reply.headers["content-type"] for reply in replies} == {"application/problem+json"}


@pytest.mark.anyio
async def test_given_requests_when_listed_with_limit_then_newest_come_first(database: Database) -> None:
    """Given three captured requests, when two are listed, then the two newest come back, newest first."""
    # Given
    async with api_client(database) as client:
        bin_id = (await client.post("/api/v1/bins")).json()["id"]
        ids = [(await client.post(f"/api/webhook/{bin_id}/{n}")).json()["request_id"] for n in range(3)]
        # When
        rows = (await client.get(f"/api/v1/bins/{bin_id}/requests", params={"limit": 2})).json()
    # Then
    assert [row["id"] for row in rows] == [ids[2], ids[1]]
    assert rows[0]["path"] == "/2"


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, 101])
async def test_given_limit_out_of_range_when_listed_then_422(database: Database, limit: int) -> None:
    """Given a limit below 1 or above 100, when requests are listed, then the reply is 422."""
    # Given
    async with api_client(database) as client:
        bin_id = (await client.post("/api/v1/bins")).json()["id"]
        # When
        response = await client.get(f"/api/v1/bins/{bin_id}/requests", params={"limit": limit})
    # Then
    assert response.status_code == 422


@pytest.mark.anyio
async def test_given_text_and_binary_bodies_when_read_then_text_appears_only_for_utf8(database: Database) -> None:
    """Given a UTF-8 body and a binary body, when each is read, then only the UTF-8 one has body_text."""
    # Given
    async with api_client(database) as client:
        bin_id = (await client.post("/api/v1/bins")).json()["id"]
        text_id = (await client.post(f"/api/webhook/{bin_id}", content="héllo".encode())).json()["request_id"]
        binary_id = (await client.post(f"/api/webhook/{bin_id}", content=b"\xff\xfe")).json()["request_id"]
        # When
        text = (await client.get(f"/api/v1/bins/{bin_id}/requests/{text_id}")).json()
        binary = (await client.get(f"/api/v1/bins/{bin_id}/requests/{binary_id}")).json()
    # Then
    assert text["body_text"] == "héllo"
    assert binary["body_text"] is None
    assert base64.b64decode(binary["body_base64"]) == b"\xff\xfe"


@pytest.mark.anyio
async def test_given_unknown_request_when_read_then_404_problem(database: Database) -> None:
    """Given a bin without the request, when the request is read, then the reply is 404 with a problem body."""
    # Given
    async with api_client(database) as client:
        bin_id = (await client.post("/api/v1/bins")).json()["id"]
        # When
        response = await client.get(f"/api/v1/bins/{bin_id}/requests/{uuid7()}")
    # Then
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.anyio
async def test_given_unknown_api_path_when_requested_then_404_problem(database: Database) -> None:
    """Given a path under /api that no route serves, when requested, then the reply is a 404 problem body."""
    # Given
    async with api_client(database) as client:
        # When
        response = await client.get("/api/nope")
    # Then
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.anyio
async def test_given_bin_path_when_method_is_not_served_then_405_lists_every_allowed_method(
    database: Database,
) -> None:
    """Given a bin path served by one route per method, when DELETE is sent, then the 405 lists GET and PATCH."""
    # Given
    async with api_client(database) as client:
        # When
        response = await client.delete("/api/v1/bins/AbCdEfGhIjKlMnOpQrStUv")
    # Then
    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers.get_list("allow") == ["GET, PATCH"]
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.anyio
async def test_given_api_when_docs_are_requested_then_openapi_is_served_under_api(database: Database) -> None:
    """Given the API, when the docs are requested, then OpenAPI is served under /api and ReDoc is off."""
    # Given
    async with api_client(database) as client:
        # When
        schema = await client.get("/api/openapi.json")
        docs = await client.get("/api/docs")
        redoc = await client.get("/redoc")
    # Then
    assert schema.status_code == 200
    assert "/api/v1/bins" in schema.json()["paths"]
    assert docs.status_code == 200
    assert redoc.status_code == 404
