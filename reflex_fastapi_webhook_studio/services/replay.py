"""Send a captured request again, to a target the user names, under the server's replay mode."""

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import httpcore
import httpx

from reflex_fastapi_webhook_studio.domain import (
    ReplayBlockedError,
    ReplayFailedError,
    ReplayMode,
    ReplayResult,
    ReplayTargetError,
)
from reflex_fastapi_webhook_studio.log_config import short_id
from reflex_fastapi_webhook_studio.security.header_rules import HOP_BY_HOP, connection_listed
from reflex_fastapi_webhook_studio.security.ssrf import GuardedBackend, TargetNotAllowedError, resolve

if TYPE_CHECKING:
    from uuid import UUID

    from reflex_fastapi_webhook_studio.domain import CapturedRequest, NameValuePairs
    from reflex_fastapi_webhook_studio.security.ssrf import Resolver
    from reflex_fastapi_webhook_studio.services.requests import RequestService
    from reflex_fastapi_webhook_studio.settings import Settings

MAX_READ_BYTES = 1_048_576
"""The most reply bytes a replay reads."""
MAX_URL_LENGTH = 2048
SCHEMES = frozenset({"http", "https"})
# httpcore sets these from the target URL and the body.
SET_BY_CLIENT = frozenset({"host", "content-length"})

logger = logging.getLogger(__name__)


def target_url(raw: str, query_string: str) -> str:
    """Check a replay target and add the original query string to it.

    Args:
        raw: The URL the user typed.
        query_string: The original query string to add; empty to add none.

    Returns:
        The URL to send to, in ASCII form.

    Raises:
        ReplayTargetError: If the URL is not an http or https URL with a host, or holds a user name.
    """
    msg = "The target must be an http or https URL with a host, such as https://example.com/hook."
    if len(raw) > MAX_URL_LENGTH:
        raise ReplayTargetError(msg)
    try:
        url = httpx.URL(raw.strip())
    except httpx.InvalidURL:
        raise ReplayTargetError(msg) from None
    if url.scheme not in SCHEMES or not url.host or url.userinfo:
        raise ReplayTargetError(msg)
    if query_string:
        extra = query_string.encode("latin-1", errors="ignore")
        url = url.copy_with(query=url.query + b"&" + extra if url.query else extra)
    return str(url.copy_with(fragment=None))


def outbound_headers(headers: NameValuePairs) -> list[tuple[str, str]]:
    """Choose the captured headers that a replay sends on.

    Args:
        headers: The captured headers.

    Returns:
        Every header except hop-by-hop ones, Host and Content-Length.
    """
    skipped = SET_BY_CLIENT | HOP_BY_HOP | connection_listed(headers)
    return [(name, value) for name, value in headers if name.lower() not in skipped]


class ReplayService:
    """Sends captured requests to targets, with no redirects, a time limit and a cap on what it reads."""

    def __init__(self, requests: RequestService, settings: Settings, *, resolver: Resolver = resolve) -> None:
        """Set up the service.

        Args:
            requests: Reads the captured request.
            settings: The app settings, which hold the replay mode and time limit.
            resolver: Looks up target addresses in `restricted` mode; tests pass a fake one.
        """
        self._requests = requests
        self._settings = settings
        self._resolver = resolver

    async def replay(self, bin_id: str, request_id: UUID, target: str, *, keep_query: bool) -> ReplayResult:
        """Send a captured request to a target, with the same method, headers and body bytes.

        Args:
            bin_id: The bin id.
            request_id: The request id.
            target: The URL to send to.
            keep_query: Whether to add the original query string to the target.

        Returns:
            What the target sent back.

        Raises:
            ReplayBlockedError: If the target resolves to an address the replay mode does not allow.
            ReplayFailedError: If the target did not answer in time, or the connection failed.
        """
        request = await self._requests.get(bin_id, request_id)
        url = target_url(target, request.query_string if keep_query else "")
        limit_s = self._settings.replay_timeout_s
        try:
            async with asyncio.timeout(limit_s):
                result = await self._send(request, url)
        except TargetNotAllowedError:
            logger.info("Refused a replay from bin %s to an address that is not allowed", short_id(bin_id))
            msg = "Target address not allowed."
            raise ReplayBlockedError(msg) from None
        except TimeoutError, httpcore.TimeoutException:
            msg = f"The target did not answer within {limit_s} s."
            raise ReplayFailedError(msg) from None
        except httpcore.ConnectError:
            msg = "Could not connect to the target."
            raise ReplayFailedError(msg) from None
        except httpcore.NetworkError, httpcore.ProtocolError:
            msg = "The connection to the target failed before the reply ended."
            raise ReplayFailedError(msg) from None
        logger.info("Replayed a request from bin %s; the target replied %d", short_id(bin_id), result.status)
        return result

    async def _send(self, request: CapturedRequest, url: str) -> ReplayResult:
        backend = (
            GuardedBackend(resolver=self._resolver)
            if self._settings.replay_mode is ReplayMode.RESTRICTED
            else httpcore.AnyIOBackend()
        )
        started = time.perf_counter()
        async with (
            httpcore.AsyncConnectionPool(ssl_context=httpx.create_ssl_context(), network_backend=backend) as pool,
            pool.stream(
                request.method.value, url, headers=outbound_headers(request.headers), content=request.body or None
            ) as response,
        ):
            chunks: list[bytes] = []
            size = 0
            truncated = False
            async for chunk in response.aiter_stream():
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_READ_BYTES:
                    truncated = True
                    break
            reason = response.extensions.get("reason_phrase", b"")
            return ReplayResult(
                status=response.status,
                reason=reason.decode("latin-1") if isinstance(reason, bytes) else "",
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                headers=tuple((name.decode("latin-1"), value.decode("latin-1")) for name, value in response.headers),
                body=b"".join(chunks)[:MAX_READ_BYTES],
                body_truncated=truncated,
            )
