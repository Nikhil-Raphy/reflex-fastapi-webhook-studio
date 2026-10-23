"""Routes that read the requests a bin has caught."""

from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003  # FastAPI reads route annotations at run time.

from fastapi import APIRouter, Query, status

from reflex_fastapi_webhook_studio.api.schemas import RequestDetailOut
from reflex_fastapi_webhook_studio.domain import RequestSummary

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.services.requests import RequestService

MAX_LIMIT = 100
DEFAULT_LIMIT = 50


def requests_router(requests: RequestService) -> APIRouter:
    """Build the routes for captured requests.

    Args:
        requests: The request service.

    Returns:
        The router.
    """
    router = APIRouter(prefix="/api/v1/bins/{bin_id}/requests", tags=["requests"])

    @router.get(
        "",
        response_model=list[RequestSummary],
        responses={status.HTTP_404_NOT_FOUND: {"description": "No bin has this id."}},
    )
    async def list_requests(
        bin_id: str, limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    ) -> list[RequestSummary]:
        """List the newest requests of a bin, newest first."""
        return await requests.list(bin_id, limit=limit)

    @router.get("/{request_id}", responses={status.HTTP_404_NOT_FOUND: {"description": "No such bin or request."}})
    async def get_request(bin_id: str, request_id: UUID) -> RequestDetailOut:
        """Read one request with its headers, query and body."""
        return RequestDetailOut.of(await requests.get(bin_id, request_id))

    return router
