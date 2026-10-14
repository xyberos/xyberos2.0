"""Starlette-backed HTTP support, installed through the optional ``http`` extra."""

from xyberos.http.adapter import HttpAdapter
from xyberos.http.csrf import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SAFE_METHODS,
    CSRFMiddleware,
    get_csrf_token,
)
from xyberos.http.metrics import (
    DEFAULT_MAX_ROUTES,
    OTHER_ROUTE,
    UNMATCHED_ROUTE,
    RequestCount,
    RequestMetrics,
    RequestMetricsMiddleware,
)
from xyberos.http.middleware import (
    CorrelationIdMiddleware,
    ErrorMappingMiddleware,
    RequestScopeMiddleware,
)
from xyberos.http.requests import read_json_object
from xyberos.http.routing import CompiledRoute, build_endpoint, compile_route
from xyberos.http.sessions import (
    DEFAULT_SESSION_MAX_AGE,
    SESSION_COOKIE,
    InMemorySessionStore,
    Session,
    SessionMiddleware,
    SessionStore,
    get_session,
)

# The handler-compilation internals (parameter kinds, HandlerParameter, the error payload helpers,
# the correlation-id header constant, the matched-route scope key) are deliberately absent: they are
# implementation details of this package, and `docs/http.md` states the header name in prose rather
# than as an API.
__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "DEFAULT_MAX_ROUTES",
    "DEFAULT_SESSION_MAX_AGE",
    "OTHER_ROUTE",
    "SAFE_METHODS",
    "SESSION_COOKIE",
    "UNMATCHED_ROUTE",
    "CompiledRoute",
    "CorrelationIdMiddleware",
    "CSRFMiddleware",
    "ErrorMappingMiddleware",
    "HttpAdapter",
    "InMemorySessionStore",
    "RequestCount",
    "RequestMetrics",
    "RequestMetricsMiddleware",
    "RequestScopeMiddleware",
    "Session",
    "SessionMiddleware",
    "SessionStore",
    "build_endpoint",
    "compile_route",
    "get_csrf_token",
    "get_session",
    "read_json_object",
]
