"""Tests for the capture routes under /api/webhook."""

import asyncio
import base64
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event

from reflex_fastapi_webhook_studio.bus.memory_bus import MemoryBus
from reflex_fastapi_webhook_studio.domain import EventType
from reflex_fastapi_webhook_studio.services.requests import RequestService
from reflex_fastapi_webhook_studio.settings import Settings
from tests.factories import api_client

if TYPE_CHECKING:
    from httpx import AsyncClient

    from reflex_fastapi_webhook_studio.db.engine import Database

UNKNOWN_BIN = "AbCdEfGhIjKlMnOpQrStUv"


async def new_bin(client: AsyncClient) -> str:
    """Create a bin through the API.

    Args:
        client: The API client.

    Returns:
        The new bin id.
    """
    response = await client.post("/api/v1/bins", json={})
    return str(response.json()["id"])


@pytest.mark.anyio
async def test_given_bin_when_json_is_posted_then_exact_bytes_and_header_order_are_stored(database: Database) -> None:
    """Given a bin, when a client POSTs JSON, then the reply is 200 with the request id and the store holds it all."""
    # Given
    body = b'{"event": "push",  "id": 7}'
    headers = [("content-type", "application/json"), ("x-sig", "b"), ("x-a", "1"), ("x-sig", "c")]
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        # When
        response = await client.post(f"/api/webhook/{bin_id}", content=body, headers=headers)
        # Then
        assert response.status_code == 200
        request_id = response.json()["request_id"]
        assert response.json() == {"ok": True, "request_id": request_id}
        detail = (await client.get(f"/api/v1/bins/{bin_id}/requests/{request_id}")).json()
    assert base64.b64decode(detail["body_base64"]) == body
    assert [pair for pair in detail["headers"] if pair[0] in {"x-sig", "x-a"}] == [
        ["x-sig", "b"],
        ["x-a", "1"],
        ["x-sig", "c"],
    ]
    assert detail["remote_addr"] == "203.0.113.7"


@pytest.mark.anyio
async def test_given_bin_when_sub_path_and_repeated_query_arrive_then_both_are_kept(database: Database) -> None:
    """Given a bin, when a request goes to a sub-path with a repeated query key, then path and both values are kept."""
    # Given
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        # When
        response = await client.get(f"/api/webhook/{bin_id}/a/b?x=1&x=2")
        detail = (await client.get(f"/api/v1/bins/{bin_id}/requests/{response.json()['request_id']}")).json()
    # Then
    assert detail["path"] == "/a/b"
    assert detail["query_string"] == "x=1&x=2"
    assert detail["query_params"] == [["x", "1"], ["x", "2"]]


@pytest.mark.anyio
async def test_given_full_bin_when_one_more_arrives_then_oldest_is_gone_and_500_remain(database: Database) -> None:
    """Given a bin with 500 requests, when one more arrives, then the oldest is gone and 500 remain."""
    # Given
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        first = (await client.post(f"/api/webhook/{bin_id}", content=b"0")).json()["request_id"]
        for n in range(1, 500):
            await client.post(f"/api/webhook/{bin_id}", content=str(n).encode())
        # When
        await client.post(f"/api/webhook/{bin_id}", content=b"new")
    # Then
    rows = await RequestService(database).list(bin_id, limit=1000)
    assert len(rows) == 500
    assert first not in {str(row.id) for row in rows}


@pytest.mark.anyio
async def test_given_no_bin_when_request_arrives_then_404_problem(database: Database) -> None:
    """Given no bin with that id, when a client sends a request, then the reply is 404 with a problem body."""
    # Given
    async with api_client(database) as client:
        # When
        response = await client.post(f"/api/webhook/{UNKNOWN_BIN}", content=b"x")
    # Then
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 404


@pytest.mark.anyio
async def test_given_malformed_bin_id_when_request_arrives_then_404_and_database_untouched(database: Database) -> None:
    """Given a malformed bin id, when a client sends a request, then the reply is 404 and no SQL runs."""
    # Given
    statements: list[str] = []
    event.listen(database.engine.sync_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    async with api_client(database) as client:
        # When
        response = await client.post("/api/webhook/short", content=b"x")
    # Then
    assert response.status_code == 404
    assert not statements


@pytest.mark.anyio
async def test_given_cors_on_when_browser_sends_preflight_then_reply_allows_and_preflight_is_stored(
    database: Database,
) -> None:
    """Given CORS is on, when a browser sends a preflight, then the reply allows it and the preflight is stored."""
    # Given
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        # When
        response = await client.options(
            f"/api/webhook/{bin_id}",
            headers={
                "origin": "https://sender.example",
                "access-control-request-method": "PUT",
                "access-control-request-headers": "x-sig, content-type",
            },
        )
        rows = (await client.get(f"/api/v1/bins/{bin_id}/requests")).json()
    # Then
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "PUT"
    assert response.headers["access-control-allow-headers"] == "x-sig, content-type"
    assert "access-control-allow-credentials" not in response.headers
    assert [(row["method"], row["reply_status"]) for row in rows] == [("OPTIONS", 204)]


@pytest.mark.anyio
async def test_given_cors_off_when_requests_arrive_then_no_cors_headers(database: Database) -> None:
    """Given CORS is off, when a request and a preflight arrive, then neither reply has CORS headers."""
    # Given
    async with api_client(database, Settings(cors_enabled=False)) as client:
        bin_id = await new_bin(client)
        # When
        post = await client.post(f"/api/webhook/{bin_id}", content=b"x", headers={"origin": "https://a.example"})
        preflight = await client.options(
            f"/api/webhook/{bin_id}",
            headers={"origin": "https://a.example", "access-control-request-method": "PUT"},
        )
    # Then
    assert post.status_code == 200
    assert preflight.status_code == 200
    assert not any(name.startswith("access-control-") for name in [*post.headers, *preflight.headers])


@pytest.mark.anyio
async def test_given_body_over_cap_when_it_arrives_then_413_and_record_without_body(database: Database) -> None:
    """Given a body over the cap, when it arrives, then the reply is 413 and a record with no body is kept."""
    # Given
    async with api_client(database, Settings(max_body_bytes=10)) as client:
        bin_id = await new_bin(client)
        # When
        response = await client.post(f"/api/webhook/{bin_id}", content=b"x" * 50)
        # Then
        assert response.status_code == 413
        assert response.headers["content-type"] == "application/problem+json"
        detail = (await client.get(f"/api/v1/bins/{bin_id}/requests/{response.json()['request_id']}")).json()
    assert detail["body_base64"] == ""
    assert detail["body_truncated"] is True
    assert detail["body_size"] == 50
    assert detail["reply_status"] == 413


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["ok", "unknown", "malformed", "too-big", "preflight", "head", "not-allowed"])
async def test_given_any_capture_reply_when_sent_then_it_carries_sandbox_and_nosniff(
    database: Database, case: str
) -> None:
    """Given any capture reply, when it is sent, then it carries CSP sandbox and nosniff."""
    # Given
    async with api_client(database, Settings(max_body_bytes=10)) as client:
        bin_id = await new_bin(client)
        # When
        match case:
            case "ok":
                response = await client.post(f"/api/webhook/{bin_id}", content=b"x")
            case "unknown":
                response = await client.post(f"/api/webhook/{UNKNOWN_BIN}", content=b"x")
            case "malformed":
                response = await client.post("/api/webhook/short", content=b"x")
            case "too-big":
                response = await client.post(f"/api/webhook/{bin_id}", content=b"x" * 50)
            case "preflight":
                response = await client.options(
                    f"/api/webhook/{bin_id}", headers={"access-control-request-method": "POST"}
                )
            case "head":
                response = await client.head(f"/api/webhook/{bin_id}")
            case _:
                response = await client.request("TRACE", f"/api/webhook/{bin_id}")
    # Then
    assert response.headers.get_list("content-security-policy") == ["sandbox"]
    assert response.headers.get_list("x-content-type-options") == ["nosniff"]
    assert response.headers.get_list("access-control-allow-origin") == ["*"]


@pytest.mark.anyio
async def test_given_bin_when_head_arrives_then_reply_has_no_body(database: Database) -> None:
    """Given a bin, when a HEAD request arrives, then the reply is 200 with no body."""
    # Given
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        # When
        response = await client.head(f"/api/webhook/{bin_id}")
    # Then
    assert response.status_code == 200
    assert response.content == b""


@pytest.mark.anyio
async def test_given_bin_when_trace_arrives_then_it_is_refused(database: Database) -> None:
    """Given a bin, when a TRACE request arrives, then the reply is 405 listing every capture method."""
    # Given
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        # When
        response = await client.request("TRACE", f"/api/webhook/{bin_id}")
        rows = (await client.get(f"/api/v1/bins/{bin_id}/requests")).json()
    # Then
    assert response.status_code == 405
    assert response.headers.get_list("allow") == ["GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS"]
    assert rows == []


async def set_reply(client: AsyncClient, bin_id: str, **reply: object) -> None:
    """Change a bin's reply through the API.

    Args:
        client: The API client.
        bin_id: The bin id.
        **reply: The reply fields.
    """
    response = await client.patch(f"/api/v1/bins/{bin_id}", json={"reply": reply})
    assert response.status_code == 200


@pytest.mark.anyio
async def test_given_bin_set_to_418_with_json_when_request_arrives_then_sender_gets_it(database: Database) -> None:
    """Given a bin set to reply 418 with a JSON body and a header, when a request arrives, then the sender gets them."""
    # Given
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        await set_reply(
            client, bin_id, status=418, content_type="application/json", headers=[["X-Tea", "yes"]], body='{"t": 1}'
        )
        # When
        response = await client.post(f"/api/webhook/{bin_id}", content=b"x")
        head = await client.head(f"/api/webhook/{bin_id}")
        rows = (await client.get(f"/api/v1/bins/{bin_id}/requests")).json()
    # Then
    assert (response.status_code, response.content) == (418, b'{"t": 1}')
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-tea"] == "yes"
    assert response.headers.get_list("content-security-policy") == ["sandbox"]
    assert response.headers.get_list("x-content-type-options") == ["nosniff"]
    assert (head.status_code, head.content) == (418, b"")
    assert [row["reply_status"] for row in rows] == [418, 418]


@pytest.mark.anyio
async def test_given_custom_status_without_body_when_request_arrives_then_default_json_goes_out(
    database: Database,
) -> None:
    """Given a bin set to 202 with no body, when a request arrives, then the default JSON body goes with that status."""
    # Given
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        await set_reply(client, bin_id, status=202)
        # When
        response = await client.post(f"/api/webhook/{bin_id}", content=b"x")
    # Then
    assert response.status_code == 202
    assert response.json() == {"ok": True, "request_id": response.json()["request_id"]}


@pytest.mark.anyio
async def test_given_text_body_or_no_content_status_when_sent_then_content_type_and_body_fit(
    database: Database,
) -> None:
    """Given a plain text reply, then a 204 reply, when requests arrive, then the type and body fit each."""
    # Given
    async with api_client(database) as client:
        bin_id = await new_bin(client)
        await set_reply(client, bin_id, body="plain words")
        # When
        text = await client.post(f"/api/webhook/{bin_id}", content=b"x")
        await set_reply(client, bin_id, status=204)
        empty = await client.post(f"/api/webhook/{bin_id}", content=b"x")
    # Then
    assert (text.status_code, text.text) == (200, "plain words")
    assert text.headers["content-type"] == "text/plain; charset=utf-8"
    assert (empty.status_code, empty.content) == (204, b"")
    assert "content-type" not in empty.headers


@pytest.mark.anyio
async def test_given_bin_with_delay_when_request_arrives_then_event_comes_before_the_reply(database: Database) -> None:
    """Given a bin with a 300 ms delay, when a request arrives, then open pages hear of it before the sender's reply."""
    # Given
    bus = MemoryBus()
    async with api_client(database, bus=bus) as client:
        bin_id = await new_bin(client)
        await set_reply(client, bin_id, delay_ms=300)
        async with bus.subscribe(bin_id) as events:
            # When
            sending = asyncio.create_task(client.post(f"/api/webhook/{bin_id}", content=b"x"))
            heard = await events.next(2)
            waiting = not sending.done()
            response = await sending
    # Then
    assert heard is not None
    assert heard.type is EventType.REQUEST_CAPTURED
    assert waiting
    assert response.status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("peer", "forwarded", "stored"),
    [
        ("203.0.113.7", "198.51.100.1", "203.0.113.7"),
        ("127.0.0.1", "198.51.100.1, 192.0.2.9", "192.0.2.9"),
        ("::1", "192.0.2.9", "192.0.2.9"),
        ("127.0.0.1", None, "127.0.0.1"),
    ],
)
async def test_given_request_through_local_proxy_when_captured_then_forwarded_address_is_kept(
    database: Database, peer: str, forwarded: str | None, stored: str
) -> None:
    """Given a request from a peer, when captured, then X-Forwarded-For counts only from a proxy on this machine."""
    # Given
    headers = {} if forwarded is None else {"x-forwarded-for": forwarded}
    async with api_client(database, client_host=peer) as client:
        bin_id = await new_bin(client)
        # When
        response = await client.post(f"/api/webhook/{bin_id}", content=b"x", headers=headers)
        detail = (await client.get(f"/api/v1/bins/{bin_id}/requests/{response.json()['request_id']}")).json()
    # Then
    assert detail["remote_addr"] == stored
