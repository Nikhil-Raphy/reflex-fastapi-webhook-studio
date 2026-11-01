"""Tests for the routes that filter, delete, export, copy and replay requests, and change a bin's reply."""

import json
from typing import TYPE_CHECKING
from uuid import uuid7

import pytest

from reflex_fastapi_webhook_studio.domain import ReplayMode
from reflex_fastapi_webhook_studio.settings import Settings
from tests.factories import api_client

if TYPE_CHECKING:
    from httpx import AsyncClient

    from reflex_fastapi_webhook_studio.db.engine import Database
    from tests.echo import EchoServer

UNKNOWN_BIN = "AbCdEfGhIjKlMnOpQrStUv"
LOCAL = Settings(replay_mode=ReplayMode.LOCAL, replay_timeout_s=1)


async def bin_with(client: AsyncClient, *bodies: tuple[str, str, bytes]) -> tuple[str, list[str]]:
    """Make a bin and send it requests.

    Args:
        client: The API client.
        *bodies: For each request, its method, sub-path and body.

    Returns:
        The bin id and the request ids, oldest first.
    """
    bin_id = (await client.post("/api/v1/bins")).json()["id"]
    ids = []
    for method, path, body in bodies:
        reply = await client.request(method, f"/api/webhook/{bin_id}{path}", content=body)
        ids.append(reply.json()["request_id"])
    return bin_id, ids


@pytest.mark.anyio
async def test_given_get_and_post_requests_when_filtered_then_only_matches_list(database: Database) -> None:
    """Given GET and POST requests, when listed by method, by search or a page at a time, then only matches show."""
    # Given
    async with api_client(database) as client:
        bin_id, ids = await bin_with(
            client, ("GET", "/a", b""), ("POST", "/b", b'{"kind": "invoice"}'), ("POST", "/c", b"other")
        )
        base = f"/api/v1/bins/{bin_id}/requests"
        # When
        posts = (await client.get(base, params={"method": "POST"})).json()
        invoice = (await client.get(base, params={"q": "INVOICE"})).json()
        page = (await client.get(base, params={"limit": 1, "before": ids[2]})).json()
        bad_method = await client.get(base, params={"method": "TRACE"})
        long_query = await client.get(base, params={"q": "x" * 201})
    # Then
    assert [row["id"] for row in posts] == [ids[2], ids[1]]
    assert [row["id"] for row in invoice] == [ids[1]]
    assert [row["id"] for row in page] == [ids[1]]
    assert (bad_method.status_code, long_query.status_code) == (422, 422)


@pytest.mark.anyio
async def test_given_requests_when_one_is_deleted_and_bin_cleared_then_they_are_gone(database: Database) -> None:
    """Given two requests, when one is deleted and then the bin cleared, then each reply is 204 and none remain."""
    # Given
    async with api_client(database) as client:
        bin_id, ids = await bin_with(client, ("POST", "", b"1"), ("POST", "", b"2"))
        base = f"/api/v1/bins/{bin_id}/requests"
        # When
        deleted = await client.delete(f"{base}/{ids[0]}")
        again = await client.delete(f"{base}/{ids[0]}")
        cleared = await client.delete(base)
        left = (await client.get(base)).json()
        unknown = await client.delete(f"/api/v1/bins/{UNKNOWN_BIN}/requests")
    # Then
    assert (deleted.status_code, again.status_code, cleared.status_code) == (204, 404, 204)
    assert left == []
    assert unknown.status_code == 404


@pytest.mark.anyio
async def test_given_bin_when_deleted_then_it_and_its_capture_url_are_gone(database: Database) -> None:
    """Given a bin with a request, when deleted, then the reply is 204 and the bin and capture URL give 404."""
    # Given
    async with api_client(database) as client:
        bin_id, _ = await bin_with(client, ("POST", "", b"x"))
        # When
        deleted = await client.delete(f"/api/v1/bins/{bin_id}")
        again = await client.delete(f"/api/v1/bins/{bin_id}")
        read = await client.get(f"/api/v1/bins/{bin_id}")
        captured = await client.post(f"/api/webhook/{bin_id}", content=b"y")
    # Then
    assert [r.status_code for r in (deleted, again, read, captured)] == [204, 404, 404, 404]


@pytest.mark.anyio
async def test_given_bin_when_exported_then_the_download_matches_the_export_format(database: Database) -> None:
    """Given a bin with two requests, when exported, then the download is JSON in the export format with both."""
    # Given
    async with api_client(database) as client:
        bin_id, ids = await bin_with(client, ("POST", "/x", b'{"a": 1}'), ("PUT", "/y", b"\x00\xff"))
        # When
        response = await client.get(f"/api/v1/bins/{bin_id}/export")
        unknown = await client.get(f"/api/v1/bins/{UNKNOWN_BIN}/export")
    # Then
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == f'attachment; filename="webhook-studio-{bin_id[:6]}.json"'
    document = json.loads(response.content)
    assert document["format"] == "webhook-studio-export"
    assert [entry["id"] for entry in document["requests"]] == ids
    assert unknown.status_code == 404


@pytest.mark.anyio
async def test_given_request_when_copied_as_curl_then_command_points_at_the_bin(database: Database) -> None:
    """Given a request, when copied as curl, then the command is plain text aimed at the bin's own URL."""
    # Given
    async with api_client(database) as client:
        bin_id, ids = await bin_with(client, ("PATCH", "/items/4?x=1", b"it's"))
        base = f"/api/v1/bins/{bin_id}/requests"
        # When
        response = await client.get(f"{base}/{ids[0]}/curl")
        unknown = await client.get(f"{base}/{uuid7()}/curl")
    # Then
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.startswith(f"curl -X PATCH 'http://test/api/webhook/{bin_id}/items/4?x=1'")
    assert "--data-raw 'it'\"'\"'s'" in response.text
    assert unknown.status_code == 404


@pytest.mark.anyio
async def test_given_public_base_url_when_copied_as_curl_then_it_names_the_public_host(database: Database) -> None:
    """Given a public base URL, when a request is copied as curl, then the command uses that host."""
    # Given
    async with api_client(database, Settings(public_base_url="https://hooks.example.com")) as client:
        bin_id, ids = await bin_with(client, ("GET", "", b""))
        # When
        response = await client.get(f"/api/v1/bins/{bin_id}/requests/{ids[0]}/curl")
    # Then
    assert response.text.startswith(f"curl -X GET https://hooks.example.com/api/webhook/{bin_id}")


@pytest.mark.anyio
async def test_given_bin_when_reply_is_patched_then_it_is_kept_and_null_restores_it(database: Database) -> None:
    """Given a bin, when its reply is patched, then the bin holds it; `reply: null` restores the default."""
    # Given
    reply = {"status": 418, "headers": [["X-Tea", "yes"]], "body": "short and stout", "delay_ms": 0}
    async with api_client(database) as client:
        bin_id = (await client.post("/api/v1/bins", json={"label": "tea"})).json()["id"]
        # When
        patched = await client.patch(f"/api/v1/bins/{bin_id}", json={"reply": reply})
        both = await client.patch(f"/api/v1/bins/{bin_id}", json={"label": None, "reply": None})
        nothing = await client.patch(f"/api/v1/bins/{bin_id}", json={})
    # Then
    assert patched.status_code == 200
    assert patched.json()["label"] == "tea"
    assert patched.json()["reply"] == {**reply, "content_type": None}
    assert both.json()["label"] is None
    assert both.json()["reply"] == {"status": 200, "content_type": None, "headers": [], "body": None, "delay_ms": 0}
    assert nothing.json() == both.json()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reply",
    [
        {"headers": [["X-Bad", "a\r\nSet-Cookie: x=y"]]},
        {"headers": [["Set-Cookie", "a=b"]]},
        {"status": 99},
        {"delay_ms": 30_001},
        {"body": "x", "status": 204},
        {"unknown": 1},
    ],
)
async def test_given_reply_that_breaks_a_rule_when_patched_then_422_and_label_kept(
    database: Database, reply: dict[str, object]
) -> None:
    """Given reply settings with CR or LF, Set-Cookie, a bad status or delay, when patched, then the reply is 422."""
    # Given
    async with api_client(database) as client:
        bin_id = (await client.post("/api/v1/bins", json={"label": "kept"})).json()["id"]
        # When
        response = await client.patch(f"/api/v1/bins/{bin_id}", json={"label": "new", "reply": reply})
        after = (await client.get(f"/api/v1/bins/{bin_id}")).json()
    # Then
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert after["label"] == "kept"


@pytest.mark.anyio
async def test_given_restricted_mode_when_replayed_to_loopback_then_403_not_allowed(
    database: Database, echo_server: EchoServer
) -> None:
    """Given `restricted` mode, when a request is replayed to 127.0.0.1, then the reply is 403 and nothing is sent."""
    # Given
    async with api_client(database) as client:
        bin_id, ids = await bin_with(client, ("POST", "", b"x"))
        # When
        response = await client.post(
            f"/api/v1/bins/{bin_id}/requests/{ids[0]}/replay", json={"target_url": f"{echo_server.url}/hook"}
        )
    # Then
    assert response.status_code == 403
    assert response.json()["detail"] == "Target address not allowed."
    assert echo_server.received == []


@pytest.mark.anyio
async def test_given_local_mode_when_replayed_then_same_method_body_and_headers_arrive(
    database: Database, echo_server: EchoServer
) -> None:
    """Given `local` mode, when replayed to an echo server, then it gets the same method, body and headers."""
    # Given
    headers = {"content-type": "application/json", "x-sig": "abc", "connection": "keep-alive"}
    async with api_client(database, LOCAL) as client:
        bin_id = (await client.post("/api/v1/bins")).json()["id"]
        sent = await client.put(f"/api/webhook/{bin_id}/orig?x=1", content=b'{"a": 1}', headers=headers)
        request_id = sent.json()["request_id"]
        # When
        response = await client.post(
            f"/api/v1/bins/{bin_id}/requests/{request_id}/replay",
            json={"target_url": f"{echo_server.url}/hook?y=2"},
        )
        plain = await client.post(
            f"/api/v1/bins/{bin_id}/requests/{request_id}/replay",
            json={"target_url": f"{echo_server.url}/plain", "use_original_query": False},
        )
    # Then
    result = response.json()
    assert (result["status"], result["reason"], result["body_text"], result["body_truncated"]) == (
        201,
        "Created",
        '{"echo": true}',
        False,
    )
    assert ["X-Echo", "yes"] in result["headers"]
    first, second = echo_server.received
    assert (first.method, first.path, first.body) == ("PUT", "/hook?y=2&x=1", b'{"a": 1}')
    assert ("x-sig", "abc") in first.headers
    assert ("connection", "keep-alive") not in first.headers
    assert second.path == "/plain"
    assert plain.status_code == 200


@pytest.mark.anyio
async def test_given_local_mode_when_replayed_then_every_header_but_hop_by_hop_ones_arrives_in_order(
    database: Database, echo_server: EchoServer
) -> None:
    """Given `local` mode, when replayed, then every captured header arrives in order, less hop-by-hop ones."""
    # Given
    headers = [
        ("x-first", "1"),
        ("connection", "keep-alive, x-drop"),
        ("keep-alive", "timeout=5"),
        ("te", "trailers"),
        ("upgrade", "h2c"),
        ("proxy-connection", "close"),
        ("x-drop", "named by Connection"),
        ("x-dup", "a"),
        ("authorization", "Bearer kept"),
        ("x-dup", "b"),
    ]
    hop_by_hop = {"connection", "keep-alive", "te", "upgrade", "proxy-connection", "x-drop"}
    # The HTTP client sets these two from the target URL and the body.
    set_by_client = {"host", "content-length"}
    async with api_client(database, LOCAL) as client:
        bin_id = (await client.post("/api/v1/bins")).json()["id"]
        sent = await client.post(f"/api/webhook/{bin_id}", content=b"x", headers=headers)
        request_id = sent.json()["request_id"]
        stored = (await client.get(f"/api/v1/bins/{bin_id}/requests/{request_id}")).json()["headers"]
        # When
        await client.post(
            f"/api/v1/bins/{bin_id}/requests/{request_id}/replay", json={"target_url": f"{echo_server.url}/all"}
        )
    # Then
    assert hop_by_hop <= {name for name, _ in stored}
    expected = [(name, value) for name, value in stored if name not in hop_by_hop | set_by_client]
    arrived = [(name, value) for name, value in echo_server.received[0].headers if name not in set_by_client]
    assert arrived == expected
    assert [value for name, value in arrived if name == "x-dup"] == ["a", "b"]


@pytest.mark.anyio
async def test_given_local_mode_when_target_redirects_or_is_large_then_not_followed_and_cut(
    database: Database, echo_server: EchoServer
) -> None:
    """Given `local` mode, when the target redirects or sends over 1 MiB, then the redirect is not followed."""
    # Given
    async with api_client(database, LOCAL) as client:
        bin_id, ids = await bin_with(client, ("POST", "", b"x"))
        url = f"/api/v1/bins/{bin_id}/requests/{ids[0]}/replay"
        # When
        redirect = (await client.post(url, json={"target_url": f"{echo_server.url}/redirect"})).json()
        big = (await client.post(url, json={"target_url": f"{echo_server.url}/big"})).json()
    # Then
    assert redirect["status"] == 302
    assert [path for path in (r.path for r in echo_server.received) if path.startswith("/else")] == []
    assert big["body_truncated"] is True
    assert len(big["body_text"]) == 1_048_576


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("target", "status", "detail"),
    [
        ("ftp://example.com/", 422, "http or https URL"),
        ("SLOW", 502, "did not answer within 1 s"),
        ("http://127.0.0.1:9/", 502, "Could not connect"),
    ],
)
async def test_given_bad_slow_or_closed_target_when_replayed_then_a_problem_says_why(
    database: Database, echo_server: EchoServer, target: str, status: int, detail: str
) -> None:
    """Given a target that is not http, too slow or closed, when replayed, then the problem body says which."""
    # Given
    async with api_client(database, LOCAL) as client:
        bin_id, ids = await bin_with(client, ("POST", "", b"x"))
        target_url = f"{echo_server.url}/slow" if target == "SLOW" else target
        # When
        response = await client.post(f"/api/v1/bins/{bin_id}/requests/{ids[0]}/replay", json={"target_url": target_url})
        unknown = await client.post(
            f"/api/v1/bins/{bin_id}/requests/{uuid7()}/replay", json={"target_url": "https://example.com"}
        )
    # Then
    assert response.status_code == status
    assert detail in response.json()["detail"]
    assert unknown.status_code == 404
