"""Build a curl command that sends a captured request again, to the bin's own URL."""

import base64
import shlex
from typing import TYPE_CHECKING

from reflex_fastapi_webhook_studio.domain import HttpMethod
from reflex_fastapi_webhook_studio.security.header_rules import HOP_BY_HOP, connection_listed

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.domain import CapturedRequest

# curl sets these from the URL and the body it sends.
SET_BY_CURL = frozenset({"host", "content-length"})
LINE_BREAK = " \\\n  "


def curl_command(request: CapturedRequest, capture_url: str) -> str:
    """Build a shell command that sends the same method, path, query, headers and body bytes to a bin.

    Every value is shell-quoted. A body that is not UTF-8 text goes through base64, so its bytes survive the shell.

    Args:
        request: The captured request.
        capture_url: The bin's capture URL.

    Returns:
        The command, split over lines.
    """
    url = capture_url if request.path == "/" else f"{capture_url}{request.path}"
    if request.query_string:
        url = f"{url}?{request.query_string}"
    method = ["--head"] if request.method is HttpMethod.HEAD else ["-X", request.method.value]
    parts = [shlex.join(["curl", *method, url])]
    skipped = SET_BY_CURL | HOP_BY_HOP | connection_listed(request.headers)
    parts.extend(
        f"-H {shlex.quote(f'{name}: {value}')}" for name, value in request.headers if name.lower() not in skipped
    )
    if not request.body:
        return LINE_BREAK.join(parts)
    if request.content_type is None:
        # Without this, curl labels the body as a form.
        parts.append("-H content-type:")
    text = _text(request.body)
    if text is not None:
        parts.append(f"--data-raw {shlex.quote(text)}")
        return LINE_BREAK.join(parts)
    parts.append("--data-binary @-")
    encoded = base64.b64encode(request.body).decode("ascii")
    return f"printf %s {shlex.quote(encoded)} | base64 -d | {LINE_BREAK.join(parts)}"


def _text(body: bytes) -> str | None:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # A shell argument cannot hold NUL.
    return None if "\x00" in text else text
