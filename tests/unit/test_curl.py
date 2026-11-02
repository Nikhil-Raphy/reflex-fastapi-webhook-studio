"""Tests for the curl command built from a captured request."""

import shutil
import subprocess
from dataclasses import replace

import pytest

from reflex_fastapi_webhook_studio.domain import HttpMethod, body_preview
from reflex_fastapi_webhook_studio.services.curl import curl_command
from tests.echo import EchoServer
from tests.factories import make_request

BIN_ID = "AbCdEfGhIjKlMnOpQrStUv"
URL = f"https://studio.example.com/api/webhook/{BIN_ID}"
needs_curl = pytest.mark.skipif(shutil.which("curl") is None or shutil.which("bash") is None, reason="needs curl")


def run(command: str) -> None:
    """Run a command in bash and fail the test if it fails.

    Args:
        command: The shell command.
    """
    # The command comes from the code under test; running it is the point of the test.
    subprocess.run(["bash", "-c", command], check=True, capture_output=True, timeout=30)  # noqa: S603, S607


def test_given_json_request_when_copied_as_curl_then_method_url_headers_and_body_are_quoted() -> None:
    """Given a JSON POST with hop-by-hop headers, when copied as curl, then those headers are dropped."""
    # Given
    request = replace(
        make_request(BIN_ID),
        headers=(
            ("host", "old.example.com"),
            ("content-type", "application/json"),
            ("content-length", "8"),
            ("connection", "keep-alive, x-hop"),
            ("x-hop", "1"),
            ("x-sig", "it's"),
        ),
    )
    # When
    command = curl_command(request, URL)
    # Then
    assert command.startswith(f"curl -X POST '{URL}/github?x=1&x=2'")
    assert "-H 'content-type: application/json'" in command
    assert "-H 'x-sig: it'\"'\"'s'" in command
    assert "host:" not in command
    assert "content-length" not in command
    assert "x-hop" not in command
    assert "--data-raw '{\"a\": 1}'" in command


@pytest.mark.parametrize(("method", "start"), [(HttpMethod.GET, "curl -X GET"), (HttpMethod.HEAD, "curl --head")])
def test_given_request_without_body_when_copied_then_no_data_is_sent(method: HttpMethod, start: str) -> None:
    """Given a GET or HEAD to the bin's own URL with no body, when copied as curl, then the command sends no data."""
    # Given
    request = replace(make_request(BIN_ID, body=b""), method=method, path="/", query_string="")
    # When
    command = curl_command(request, URL)
    # Then
    assert command.startswith(f"{start} {URL}")
    assert "--data" not in command


@needs_curl
@pytest.mark.parametrize(
    "body",
    [
        b'line one\nit\'s "quoted" $HOME `ls`\r\nend',
        b"@not-a-file",
        bytes(range(256)),
    ],
)
def test_given_awkward_body_when_curl_command_runs_then_the_bin_receives_the_same_bytes(body: bytes) -> None:
    """Given a body with quotes, newlines, a leading @ or binary bytes, when the command runs, then the bytes match."""
    # Given
    request = replace(make_request(BIN_ID, body=body), body_preview=body_preview(body))
    with EchoServer() as server:
        command = curl_command(request, f"{server.url}/api/webhook/{BIN_ID}")
        # When
        run(command)
    # Then
    assert len(server.received) == 1
    received = server.received[0]
    assert (received.method, received.path, received.body) == ("POST", f"/api/webhook/{BIN_ID}/github?x=1&x=2", body)
    assert ("content-type", "application/json") in received.headers


@needs_curl
def test_given_body_without_content_type_when_command_runs_then_curl_adds_none() -> None:
    """Given a body sent with no content type, when the command runs, then curl does not label it as a form."""
    # Given
    request = replace(make_request(BIN_ID, body=b"a=b"), headers=(("x-a", "1"),), content_type=None)
    with EchoServer() as server:
        command = curl_command(request, f"{server.url}/api/webhook/{BIN_ID}")
        # When
        run(command)
    # Then
    assert len(server.received) == 1
    received = server.received[0]
    assert received.body == b"a=b"
    assert "content-type" not in {name for name, _ in received.headers}
