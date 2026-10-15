"""Routes that create, read and rename bins."""

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, status

from reflex_fastapi_webhook_studio.api.schemas import BinCreate, BinUpdate  # noqa: TC001  # FastAPI reads them at run time.
from reflex_fastapi_webhook_studio.domain import Bin

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.services.bins import BinService

NOT_FOUND: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"description": "No bin has this id."}}


def bins_router(bins: BinService) -> APIRouter:
    """Build the routes for bins.

    Args:
        bins: The bin service.

    Returns:
        The router.
    """
    router = APIRouter(prefix="/api/v1/bins", tags=["bins"])

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=Bin,
        responses={status.HTTP_409_CONFLICT: {"description": "The app holds the most bins it may."}},
    )
    async def create_bin(body: BinCreate | None = None) -> Bin:
        """Create a bin with a new secret id. The label is optional."""
        return await bins.create(None if body is None else body.label)

    @router.get("/{bin_id}", response_model=Bin, responses=NOT_FOUND)
    async def get_bin(bin_id: str) -> Bin:
        """Read a bin."""
        return await bins.get(bin_id)

    @router.patch("/{bin_id}", response_model=Bin, responses=NOT_FOUND)
    async def update_bin(bin_id: str, body: BinUpdate) -> Bin:
        """Change the label of a bin; `null` clears it."""
        return await bins.rename(bin_id, body.label)

    return router
