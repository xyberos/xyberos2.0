"""Middleware that owns correlation IDs, request-scope lifetime, and error normalization.

The order is fixed by :class:`xyberos.http.adapter.HttpAdapter`: correlation ID (outermost), error
normalization, dependency request scope, application middleware, then the router.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from xyberos.errors import HttpError, RequestValidationError
from xyberos.runtime.context import bind_correlation_id

CORRELATION_ID_HEADER = "X-Request-ID"
LOGGER = logging.getLogger("xyberos.http")


class CorrelationIdMiddleware:
    """Bind a correlation ID for the request and echo it on the response."""

    def __init__(self, app: ASGIApp, *, header: str = CORRELATION_ID_HEADER) -> None:
        self.app = app
        self.header = header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = Headers(scope=scope).get(self.header) or uuid4().hex

        async def send_with_correlation_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[self.header] = correlation_id
            await send(message)

        with bind_correlation_id(correlation_id):
            await self.app(scope, receive, send_with_correlation_id)


class ErrorMappingMiddleware:
    """Turn ``HttpError`` into its declared response and any other failure into a safe 500.

    A programmer error is never reported as a success, and an internal message is never sent to a
    client. If a response has already started, the failure is re-raised rather than corrupting an
    in-flight response.
    """

    def __init__(self, app: ASGIApp, *, logger: logging.Logger | None = None) -> None:
        self.app = app
        self.logger = logger if logger is not None else LOGGER

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track_start(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_start)
        except HttpError as error:
            if started:
                raise
            self.logger.info("request failed with %s: %s", type(error).__name__, error)
            response = JSONResponse(error_payload(error), status_code=error.status_code)
            await response(scope, receive, send)
        except Exception:
            if started:
                raise
            self.logger.exception("unhandled error while serving a request")
            response = JSONResponse(internal_error_payload(), status_code=500)
            await response(scope, receive, send)


class RequestScopeMiddleware:
    """Open the dependency request scope around everything inside it."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        request_scope: Callable[[], AbstractAsyncContextManager[object]],
    ) -> None:
        self.app = app
        self._request_scope = request_scope

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        async with self._request_scope():
            await self.app(scope, receive, send)


def error_payload(error: HttpError) -> dict[str, object]:
    """Build the client-safe body for an application-authored error."""
    details: dict[str, object] = {"type": type(error).__name__, "message": str(error)}
    if isinstance(error, RequestValidationError) and error.errors:
        details["errors"] = list(error.errors)
    return {"error": details}


def internal_error_payload() -> dict[str, object]:
    """Build the body used for failures that are not safe to expose."""
    return {
        "error": {
            "type": "InternalServerError",
            "message": "the request could not be completed",
        }
    }
