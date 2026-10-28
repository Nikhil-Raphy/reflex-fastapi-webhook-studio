"""Routes that create, read, change, delete and export bins."""

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Response, status
from fastapi.responses import StreamingResponse

from reflex_fastapi_webhook_studio.api.schemas import BinCreate, BinUpdate  # noqa: TC001  # FastAPI reads them at run time.
from reflex_fastapi_webhook_studio.domain import DEFAULT_REPLY, Bin, BinSummary

if TYPE_CHECKING:
    from reflex_fastapi_webhook_studio.services.bins import BinService
    from reflex_fastapi_webhook_studio.services.export import ExportService

NOT_FOUND: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"description": "No bin has this id."}}


def bins_router(bins: BinService, exports: ExportService) -> APIRouter:
    """Build the routes for bins.

    Args:
        bins: The bin service.
        exports: The export service.

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

    @router.get(
        "",
        response_model=list[BinSummary],
        responses={status.HTTP_404_NOT_FOUND: {"description": "Listing every bin is off."}},
    )
    async def list_bins() -> list[BinSummary]:
        """List every bin, the most recently active first. Answers only when `WEBHOOK_STUDIO_BIN_LISTING` is `all`."""
        return await bins.list_all()

    @router.get("/{bin_id}", response_model=Bin, responses=NOT_FOUND)
    async def get_bin(bin_id: str) -> Bin:
        """Read a bin, with its reply settings."""
        return await bins.get(bin_id)

    @router.patch(
        "/{bin_id}",
        response_model=Bin,
        responses=NOT_FOUND | {status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "The reply breaks a rule."}},
    )
    async def update_bin(bin_id: str, body: BinUpdate) -> Bin:
        """Change the label or the reply of a bin. Leave a field out to keep it.

        `label: null` clears the label. `reply` replaces the whole reply, and `reply: null` puts back the default.
        """
        bin_ = await bins.get(bin_id)
        # The reply goes first: it can break a rule, and then the label must stay as it was.
        if "reply" in body.model_fields_set:
            bin_ = await bins.set_reply(bin_id, DEFAULT_REPLY if body.reply is None else body.reply.to_domain())
        if "label" in body.model_fields_set:
            bin_ = await bins.rename(bin_id, body.label)
        return bin_

    @router.delete("/{bin_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
    async def delete_bin(bin_id: str) -> Response:
        """Delete a bin with every request it holds."""
        await bins.delete(bin_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/{bin_id}/export",
        response_class=StreamingResponse,
        responses=NOT_FOUND | {status.HTTP_200_OK: {"content": {"application/json": {}}}},
    )
    async def export_bin(bin_id: str) -> StreamingResponse:
        """Download the bin and every request it holds as one JSON file, requests oldest first.

        Bodies come as base64, plus `body_text` when the body is valid UTF-8.
        """
        chunks = await exports.export(bin_id)
        filename = f"webhook-studio-{bin_id[:6]}.json"
        return StreamingResponse(
            chunks, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    return router
