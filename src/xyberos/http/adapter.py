"""The Starlette adapter: compile an ``App`` into an ASGI application.

``App`` keeps owning configuration, dependency resolution, lifecycle, and route records while
Starlette owns ASGI mechanics, request/response types, and the test client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route as StarletteRoute
from starlette.types import ASGIApp

from xyberos.app import App
from xyberos.http.middleware import (
    CorrelationIdMiddleware,
    ErrorMappingMiddleware,
    RequestScopeMiddleware,
)
from xyberos.http.routing import CompiledRoute, build_endpoint, compile_route


class HttpAdapter:
    """Bind one ``App`` to Starlette without letting the runtime import Starlette.

    Middleware runs outermost to innermost in this order:

    1. correlation ID, so every log line and error response carries the request ID;
    2. error normalization, so no failure escapes as a broken response;
    3. the dependency request scope;
    4. application middleware, in the order supplied; and
    5. the router, which resolves injected dependencies per request.
    """

    def __init__(
        self,
        app: App,
        *,
        middleware: Sequence[Middleware] = (),
        request_id_header: str = "X-Request-ID",
    ) -> None:
        self.app = app
        self._middleware = tuple(middleware)
        self._request_id_header = request_id_header
        self._compiled: tuple[CompiledRoute, ...] = ()
        self._asgi_app: Starlette | None = None
        self._asgi_version = -1
        self.validate()

    def validate(self) -> tuple[CompiledRoute, ...]:
        """Inspect every handler signature and report unsupported parameters."""
        self._compiled = tuple(compile_route(route) for route in self.app.routes)
        return self._compiled

    @property
    def asgi_app(self) -> Starlette:
        """The ASGI application, rebuilt only when routes change."""
        version = self.app.route_version
        if self._asgi_app is None or self._asgi_version != version:
            self.validate()
            self._asgi_app = self._build()
            self._asgi_version = version
        return self._asgi_app

    def _build(self) -> Starlette:
        routes = [
            StarletteRoute(
                compiled.route.path,
                build_endpoint(compiled, self.app.resolve),
                methods=[compiled.route.method],
                name=compiled.route.name,
            )
            for compiled in self._compiled
        ]
        middleware: list[Middleware] = [
            Middleware(CorrelationIdMiddleware, header=self._request_id_header),
            Middleware(ErrorMappingMiddleware),
            Middleware(RequestScopeMiddleware, request_scope=self.app.request_context),
            *self._middleware,
        ]
        return Starlette(
            routes=routes,
            middleware=middleware,
            lifespan=self._lifespan,
            debug=self.app.settings.app.debug,
        )

    @asynccontextmanager
    async def _lifespan(self, _: ASGIApp) -> AsyncIterator[None]:
        self.validate()
        async with self.app.lifespan():
            yield
