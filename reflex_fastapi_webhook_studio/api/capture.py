"""Capture routes: store any request sent to a bin and send a reply."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from reflex_fastapi_webhook_studio.api.problems import problem
from reflex_fastapi_webhook_studio.api.schemas import CaptureOut
from reflex_fastapi_webhook_studio.domain import BinNotFoundError, HttpMethod, IncomingRequest, is_bin_id

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from reflex_fastapi_webhook_studio.services.capture import CaptureService
    from reflex_fastapi_webhook_studio.settings import Settings

CAPTURE_PREFIX = "/api/webhook"
# A capture reply may hold anything, so the browser must treat it as a sandboxed, opaque origin.
SAFETY_HEADERS = {"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff"}


class CaptureReplyHeaders:
    """ASGI layer that adds the safety headers, and CORS when on, to every reply under /api/webhook/.

    It also covers replies that the capture handler never builds, such as a 405 for a method it does not take.
    """

    def __init__(self, app: ASGIApp, *, cors_enabled: bool) -> None:
        """Wrap the API.

        Args:
            app: The ASGI app to wrap.
            cors_enabled: Whether capture replies carry `Access-Control-Allow-Origin: *`.
        """
        self.app = app
        headers = SAFETY_HEADERS | ({"Access-Control-Allow-Origin": "*"} if cors_enabled else {})
        self.headers = [(name.lower().encode(), value.encode()) for name, value in headers.items()]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the call on, adding the headers to a capture reply.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        if scope["type"] != "http" or not scope["path"].startswith(f"{CAPTURE_PREFIX}/"):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *self.headers]
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def read_body(request: Request, limit: int) -> tuple[bytes, int, bool]:
    """Read the body as it streams in, and stop once it passes the cap.

    Args:
        request: The request.
        limit: The most bytes to keep.

    Returns:
        The body (empty when over the cap), the bytes read, and whether reading stopped at the cap.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return b"", size, True
        chunks.append(chunk)
    return b"".join(chunks), size, False


def to_incoming(request: Request, path: str, body: bytes, size: int, *, truncated: bool) -> IncomingRequest:
    """Collect what the app stores about a request.

    Args:
        request: The request.
        path: The sub-path after the bin id, without its leading "/".
        body: The body bytes, empty when over the cap.
        size: The bytes read.
        truncated: Whether reading stopped at the cap.

    Returns:
        The request as the capture service takes it.
    """
    return IncomingRequest(
        method=HttpMethod(request.method),
        path=f"/{path}",
        query_string=request.scope["query_string"].decode("latin-1"),
        headers=tuple((name.decode("latin-1"), value.decode("latin-1")) for name, value in request.headers.raw),
        body=body,
        body_size=size,
        body_truncated=truncated,
        content_type=request.headers.get("content-type"),
        remote_addr=None if request.client is None else request.client.host,
        http_version=request.scope.get("http_version", "1.1"),
    )


def capture_router(capture: CaptureService, settings: Settings) -> APIRouter:
    """Build the capture routes, for the bin URL itself and any path under it.

    Args:
        capture: The capture service.
        settings: The app settings.

    Returns:
        The router.
    """
    router = APIRouter(prefix=CAPTURE_PREFIX, tags=["capture"])

    async def capture_request(request: Request, bin_id: str, path: str = "") -> Response:
        """Store the request in the bin and reply with its id."""
        if not is_bin_id(bin_id):
            return problem(HTTPStatus.NOT_FOUND, "No bin has this id.")
        body, size, truncated = await read_body(request, settings.max_body_bytes)
        requested_method = request.headers.get("access-control-request-method")
        preflight = settings.cors_enabled and request.method == HttpMethod.OPTIONS and requested_method is not None
        reply_status = (
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE if truncated else HTTPStatus.NO_CONTENT if preflight else HTTPStatus.OK
        )
        try:
            stored = await capture.capture(
                bin_id, to_incoming(request, path, body, size, truncated=truncated), reply_status=reply_status
            )
        except BinNotFoundError:
            return problem(HTTPStatus.NOT_FOUND, "No bin has this id.")
        if truncated:
            detail = f"The body is over {settings.max_body_bytes} bytes. The request was kept without its body."
            return problem(reply_status, detail, request_id=stored.id)
        if preflight:
            headers = {
                "Access-Control-Allow-Methods": requested_method or "",
                "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", ""),
            }
            return Response(status_code=reply_status, headers=headers)
        if request.method == HttpMethod.HEAD:
            return Response(status_code=reply_status, media_type="application/json")
        return JSONResponse(CaptureOut(ok=True, request_id=stored.id).model_dump(mode="json"))

    for route, kind in (("/{bin_id}", "bin"), ("/{bin_id}/{path:path}", "sub_path")):
        for method in HttpMethod:
            router.add_api_route(
                route,
                capture_request,
                methods=[method.value],
                response_model=CaptureOut,
                operation_id=f"capture_{method.value.lower()}_{kind}",
            )
    return router
