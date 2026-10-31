"""Routes that read, delete, copy and replay the requests a bin has caught."""

from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID  # noqa: TC003  # FastAPI reads route annotations at run time.

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from reflex_fastapi_webhook_studio.api.capture import CAPTURE_PREFIX
from reflex_fastapi_webhook_studio.api.schemas import (
    ReplayIn,
    ReplayOut,
    RequestDetailOut,
)
from reflex_fastapi_webhook_studio.domain import MAX_SEARCH_LENGTH, HttpMethod, RequestFilter, RequestSummary
from reflex_fastapi_webhook_studio.services.curl import curl_command

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.services.replay import ReplayService
    from reflex_fastapi_webhook_studio.services.requests import RequestService
    from reflex_fastapi_webhook_studio.settings import Settings

MAX_LIMIT = 100
DEFAULT_LIMIT = 50
NO_BIN: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"description": "No bin has this id."}}
NO_REQUEST: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"description": "No such bin or request."}}


def public_base(request: Request, settings: Settings) -> str:
    """Find the scheme and host that senders use.

    Args:
        request: The current request.
        settings: The app settings.

    Returns:
        `WEBHOOK_STUDIO_PUBLIC_BASE_URL` when set, or the base of the URL this request came to.
    """
    return settings.public_base_url or str(request.base_url).rstrip("/")


def requests_router(requests: RequestService, replays: ReplayService, settings: Settings) -> APIRouter:
    """Build the routes for captured requests.

    Args:
        requests: The request service.
        replays: The replay service.
        settings: The app settings.

    Returns:
        The router.
    """
    router = APIRouter(prefix="/api/v1/bins/{bin_id}/requests", tags=["requests"])

    @router.get("", response_model=list[RequestSummary], responses=NO_BIN)
    async def list_requests(
        bin_id: str,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        method: HttpMethod | None = None,
        q: Annotated[str, Query(max_length=MAX_SEARCH_LENGTH, description="Text to find, in any case.")] = "",
        before: Annotated[
            UUID | None, Query(description="Only requests older than this one, for the next page.")
        ] = None,
    ) -> list[RequestSummary]:
        """List a bin's requests, newest first.

        Filter by method, and by text found in the method, path, query string, headers or the first 4 KiB of the body.
        To read the next page, pass the id of the last request as `before`.
        """
        where = RequestFilter(method=method, text=q.strip())
        return await requests.list(bin_id, limit=limit, where=where, before=before)

    @router.delete("", status_code=status.HTTP_204_NO_CONTENT, responses=NO_BIN)
    async def clear_bin(bin_id: str) -> Response:
        """Delete every request of a bin."""
        await requests.clear(bin_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/{request_id}", responses=NO_REQUEST)
    async def get_request(bin_id: str, request_id: UUID) -> RequestDetailOut:
        """Read one request with its headers, query and body."""
        return RequestDetailOut.of(await requests.get(bin_id, request_id))

    @router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NO_REQUEST)
    async def delete_request(bin_id: str, request_id: UUID) -> Response:
        """Delete one request."""
        await requests.delete(bin_id, request_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/{request_id}/curl",
        response_class=PlainTextResponse,
        responses=NO_REQUEST | {status.HTTP_200_OK: {"content": {"text/plain": {}}}},
    )
    async def copy_as_curl(bin_id: str, request_id: UUID, request: Request) -> PlainTextResponse:
        """Give a curl command that sends the same request to the bin again, with every value shell-quoted."""
        captured = await requests.get(bin_id, request_id)
        return PlainTextResponse(curl_command(captured, f"{public_base(request, settings)}{CAPTURE_PREFIX}/{bin_id}"))

    @router.post(
        "/{request_id}/replay",
        responses=NO_REQUEST
        | {
            status.HTTP_403_FORBIDDEN: {"description": "The replay mode does not allow the target address."},
            status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "The target is not an http or https URL."},
            status.HTTP_502_BAD_GATEWAY: {"description": "The target could not be reached or did not answer."},
        },
    )
    async def replay_request(bin_id: str, request_id: UUID, body: ReplayIn) -> ReplayOut:
        """Send the request again to a target, with the same method, headers and body bytes.

        Hop-by-hop headers, Host and Content-Length are left out. Redirects are not followed, and at most 1 MiB of
        the reply is read. The result is not stored.
        """
        result = await replays.replay(bin_id, request_id, body.target_url, keep_query=body.use_original_query)
        return ReplayOut.of(result)

    return router
