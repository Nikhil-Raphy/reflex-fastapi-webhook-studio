"""Build the FastAPI app, and the ASGI layer that sends /api requests to it ahead of Reflex."""

import asyncio
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse  # noqa: TC002  # FastAPI reads route annotations at run time.
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from reflex_fastapi_webhook_studio import __version__
from reflex_fastapi_webhook_studio.api.bins import bins_router
from reflex_fastapi_webhook_studio.api.capture import CaptureReplyHeaders, capture_router
from reflex_fastapi_webhook_studio.api.problems import add_problem_handlers, problem
from reflex_fastapi_webhook_studio.api.requests import requests_router
from reflex_fastapi_webhook_studio.api.schemas import HealthOut
from reflex_fastapi_webhook_studio.security.ssrf import resolve
from reflex_fastapi_webhook_studio.services.bins import BinService
from reflex_fastapi_webhook_studio.services.capture import CaptureService
from reflex_fastapi_webhook_studio.services.export import ExportService
from reflex_fastapi_webhook_studio.services.replay import ReplayService
from reflex_fastapi_webhook_studio.services.requests import RequestService

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from redis.asyncio import Redis
    from starlette.types import ASGIApp, Receive, Scope, Send

    from reflex_fastapi_webhook_studio.bus.base import EventBus
    from reflex_fastapi_webhook_studio.db.engine import Database
    from reflex_fastapi_webhook_studio.security.ssrf import Resolver
    from reflex_fastapi_webhook_studio.settings import Settings

API_PREFIX = "/api"
HEALTH_TIMEOUT_S = 5

logger = logging.getLogger(__name__)


def health_router(database: Database, redis: Redis | None = None) -> APIRouter:
    """Build the health route.

    Args:
        database: The database to check.
        redis: The Redis client to check, when the app uses Redis.

    Returns:
        The router.
    """
    router = APIRouter(prefix="/api/v1", tags=["health"])

    @router.get(
        "/health",
        response_model=HealthOut,
        response_model_exclude_none=True,
        responses={HTTPStatus.SERVICE_UNAVAILABLE: {"description": "A check failed; the body names it."}},
    )
    async def health() -> HealthOut | JSONResponse:
        """Report that the app is up, its version, and that the database (and Redis, when used) answers."""
        try:
            async with asyncio.timeout(HEALTH_TIMEOUT_S):
                await database.check()
        except (SQLAlchemyError, OSError) as error:
            logger.warning("Health check found the database down: %s", type(error).__name__)
            return problem(HTTPStatus.SERVICE_UNAVAILABLE, "The database does not answer.", check="database")
        if redis is None:
            return HealthOut(status="ok", version=__version__, database="ok")
        try:
            async with asyncio.timeout(HEALTH_TIMEOUT_S):
                # redis-py types its sync and async clients together; this client is async.
                await cast("Awaitable[bool]", redis.ping())
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning("Health check found Redis down: %s", type(error).__name__)
            return problem(HTTPStatus.SERVICE_UNAVAILABLE, "Redis does not answer.", check="redis")
        return HealthOut(status="ok", version=__version__, database="ok", redis="ok")

    return router


def create_api(
    settings: Settings,
    database: Database,
    *,
    bus: EventBus | None = None,
    redis: Redis | None = None,
    resolver: Resolver = resolve,
) -> FastAPI:
    """Build the FastAPI app with every route.

    Args:
        settings: The app settings.
        database: The database.
        bus: The event bus the services publish on; one with no subscribers when None.
        redis: The Redis client that health checks, when the app uses Redis.
        resolver: Looks up replay target addresses; tests pass a fake one.

    Returns:
        The FastAPI app.
    """
    api = FastAPI(
        title="Reflex FastAPI Webhook Studio",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        openapi_url="/api/openapi.json",
    )
    bins = BinService(database, settings, bus=bus)
    requests = RequestService(database, bus=bus)
    replays = ReplayService(requests, settings, resolver=resolver)
    add_problem_handlers(api)
    api.add_middleware(CaptureReplyHeaders, cors_enabled=settings.cors_enabled)
    api.include_router(health_router(database, redis))
    api.include_router(bins_router(bins, ExportService(database)))
    api.include_router(requests_router(requests, replays, settings))
    api.include_router(capture_router(CaptureService(database, settings, bus=bus), bins, settings))
    return api


class ApiFirst:
    """ASGI layer that sends HTTP requests under /api to the API and everything else to Reflex.

    It sits outside Reflex's own CORS layer, so the API sets its own CORS headers and sees every preflight.
    """

    def __init__(self, api: ASGIApp, reflex_app: ASGIApp) -> None:
        """Hold both apps.

        Args:
            api: The FastAPI app.
            reflex_app: Reflex's ASGI app, which also handles lifespan and websocket traffic.
        """
        self.api = api
        self.reflex_app = reflex_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Route one ASGI call.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        path: str = scope.get("path", "")
        if scope["type"] == "http" and (path == API_PREFIX or path.startswith(f"{API_PREFIX}/")):
            await self.api(scope, receive, send)
        else:
            await self.reflex_app(scope, receive, send)
