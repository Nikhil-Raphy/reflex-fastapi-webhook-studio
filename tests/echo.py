"""A small HTTP server in a thread that records what it receives, for the curl and replay tests."""

import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Self, override

BIG_BODY_BYTES = 1_048_576 + 10
SLOW_S = 2.0


@dataclass(frozen=True, slots=True)
class Received:
    """One request the server got.

    Attributes:
        method: The HTTP method.
        path: The path with its query string.
        headers: The headers in order, names in lower case.
        body: The body bytes.
    """

    method: str
    path: str
    headers: list[tuple[str, str]]
    body: bytes


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def _handle(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length) if length else b""
        headers = [(name.lower(), value) for name, value in self.headers.items()]
        self.server.received.append(Received(method=self.command, path=self.path, headers=headers, body=body))
        if self.path.startswith("/slow"):
            time.sleep(SLOW_S)
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        reply = b"x" * BIG_BODY_BYTES if self.path.startswith("/big") else b'{"echo": true}'
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Echo", "yes")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(reply)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _handle  # noqa: N815  # http.server's names.

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Keep test output quiet."""


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    received: list[Received]


class EchoServer:
    """Runs on 127.0.0.1 on a free port while the context is open.

    Paths starting with /slow wait two seconds, /big send just over 1 MiB, /redirect send a 302; any other path
    gets 201 with a small JSON body and an `X-Echo` header.
    """

    def __init__(self) -> None:
        """Bind to a free port."""
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.received = []
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        """The server's base URL.

        Returns:
            The URL, with no trailing slash.
        """
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def received(self) -> list[Received]:
        """The requests the server got, oldest first.

        Returns:
            The requests.
        """
        return self._server.received

    def __enter__(self) -> Self:
        """Start serving.

        Returns:
            The server.
        """
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        """Stop serving and free the port."""
        self._server.shutdown()
        self._server.server_close()
