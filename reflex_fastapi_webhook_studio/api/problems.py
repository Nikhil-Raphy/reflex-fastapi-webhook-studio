"""Error replies as RFC 9457 problem details."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.routing import Match

from reflex_fastapi_webhook_studio.domain import (
    BinLimitError,
    BinNotFoundError,
    HttpMethod,
    InvalidReplyError,
    ListingOffError,
    ReplayBlockedError,
    ReplayFailedError,
    ReplayTargetError,
    RequestNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from fastapi import FastAPI, Request
    from starlette.routing import BaseRoute

PROBLEM_TYPE = "application/problem+json"


def problem(
    status: int, detail: str | None = None, *, headers: Mapping[str, str] | None = None, **extensions: object
) -> JSONResponse:
    """Build a problem details reply.

    Args:
        status: The HTTP status code.
        detail: What went wrong, for a person to read.
        headers: Extra reply headers.
        **extensions: More members to add to the body.

    Returns:
        The reply.
    """
    body: dict[str, object] = {"type": "about:blank", "title": HTTPStatus(status).phrase, "status": status}
    if detail is not None:
        body["detail"] = detail
    body.update(extensions)
    return JSONResponse(jsonable_encoder(body), status_code=status, headers=headers, media_type=PROBLEM_TYPE)


def allowed_methods(request: Request) -> list[str]:
    """List the methods that some route takes for the request's path.

    Starlette's 405 names only the methods of the first route that matches the path, but many of our paths have one
    route per method.

    Args:
        request: The request.

    Returns:
        The methods.
    """
    routes: list[BaseRoute] = request.app.router.routes
    return [
        method
        for method in HttpMethod
        if any(route.matches({**request.scope, "method": method})[0] is Match.FULL for route in routes)
    ]


DOMAIN_PROBLEMS: dict[type[Exception], tuple[HTTPStatus, str | None]] = {
    BinNotFoundError: (HTTPStatus.NOT_FOUND, "No bin has this id."),
    RequestNotFoundError: (HTTPStatus.NOT_FOUND, "The bin holds no request with this id."),
    BinLimitError: (HTTPStatus.CONFLICT, "The app holds the most bins it may."),
    ListingOffError: (HTTPStatus.NOT_FOUND, "Listing every bin is off."),
    InvalidReplyError: (HTTPStatus.UNPROCESSABLE_CONTENT, None),
    ReplayTargetError: (HTTPStatus.UNPROCESSABLE_CONTENT, None),
    ReplayBlockedError: (HTTPStatus.FORBIDDEN, None),
    ReplayFailedError: (HTTPStatus.BAD_GATEWAY, None),
}
"""Each domain error's status, and its detail; None means the error's own message."""


def _domain_handler(status: HTTPStatus, detail: str | None) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(_request: Request, error: Exception) -> JSONResponse:
        return problem(status, str(error) if detail is None else detail)

    return handle


def add_problem_handlers(api: FastAPI) -> None:
    """Turn domain errors, bad input and unknown routes into problem details replies.

    Args:
        api: The FastAPI app.
    """

    async def invalid(_request: Request, error: Exception) -> JSONResponse:
        errors = error.errors() if isinstance(error, RequestValidationError) else []
        return problem(HTTPStatus.UNPROCESSABLE_CONTENT, "The request is not valid.", errors=errors)

    async def http_error(request: Request, error: Exception) -> JSONResponse:
        if not isinstance(error, HTTPException):
            return problem(HTTPStatus.INTERNAL_SERVER_ERROR)
        headers = dict(error.headers or {})
        if error.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
            headers["Allow"] = ", ".join(allowed_methods(request))
        return problem(error.status_code, headers=headers)

    for error_type, (status, detail) in DOMAIN_PROBLEMS.items():
        api.add_exception_handler(error_type, _domain_handler(status, detail))
    api.add_exception_handler(RequestValidationError, invalid)
    api.add_exception_handler(HTTPException, http_error)
