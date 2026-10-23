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
    ListingOffError,
    RequestNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

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


def add_problem_handlers(api: FastAPI) -> None:
    """Turn domain errors, bad input and unknown routes into problem details replies.

    Args:
        api: The FastAPI app.
    """

    async def bin_not_found(_request: Request, _error: Exception) -> JSONResponse:
        return problem(HTTPStatus.NOT_FOUND, "No bin has this id.")

    async def request_not_found(_request: Request, _error: Exception) -> JSONResponse:
        return problem(HTTPStatus.NOT_FOUND, "The bin holds no request with this id.")

    async def bin_limit(_request: Request, _error: Exception) -> JSONResponse:
        return problem(HTTPStatus.CONFLICT, "The app holds the most bins it may.")

    async def listing_off(_request: Request, _error: Exception) -> JSONResponse:
        return problem(HTTPStatus.NOT_FOUND, "Listing every bin is off.")

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

    api.add_exception_handler(BinNotFoundError, bin_not_found)
    api.add_exception_handler(RequestNotFoundError, request_not_found)
    api.add_exception_handler(BinLimitError, bin_limit)
    api.add_exception_handler(ListingOffError, listing_off)
    api.add_exception_handler(RequestValidationError, invalid)
    api.add_exception_handler(HTTPException, http_error)
