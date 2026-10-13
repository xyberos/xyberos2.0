"""Starlette-backed HTTP support, installed through the optional ``http`` extra."""

from xyberos.http.adapter import HttpAdapter
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

# The handler-compilation internals (parameter kinds, HandlerParameter, the error payload helpers,
# the correlation-id header constant, the matched-route scope key) are deliberately absent: they are
# implementation details of this package, and `docs/http.md` states the header name in prose rather
# than as an API.
__all__ = [
    "DEFAULT_MAX_ROUTES",
    "OTHER_ROUTE",
    "UNMATCHED_ROUTE",
    "CompiledRoute",
    "CorrelationIdMiddleware",
    "ErrorMappingMiddleware",
    "HttpAdapter",
    "RequestCount",
    "RequestMetrics",
    "RequestMetricsMiddleware",
    "RequestScopeMiddleware",
    "build_endpoint",
    "compile_route",
    "read_json_object",
]
