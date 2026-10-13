"""Build the FastAPI app that Reflex mounts."""

from fastapi import APIRouter, FastAPI

from reflex_fastapi_webhook_studio import __version__

router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the app is up, and its version.

    Returns:
        The app status and version.
    """
    return {"status": "ok", "version": __version__}


def create_api() -> FastAPI:
    """Build the FastAPI app with every route.

    Returns:
        The FastAPI app.
    """
    api = FastAPI(
        title="Reflex FastAPI Webhook Studio",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    api.include_router(router)
    return api
