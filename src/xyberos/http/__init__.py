"""Starlette-backed HTTP support, installed through the optional ``http`` extra."""

from xyberos.http.adapter import HttpAdapter
from xyberos.http.middleware import (
    CORRELATION_ID_HEADER,
    CorrelationIdMiddleware,
    ErrorMappingMiddleware,
    RequestScopeMiddleware,
    error_payload,
    internal_error_payload,
)
from xyberos.http.requests import read_json_object
from xyberos.http.routing import (
    INJECT,
    PATH,
    REQUEST,
    CompiledRoute,
    HandlerParameter,
    build_endpoint,
    compile_route,
)

__all__ = [
    "CORRELATION_ID_HEADER",
    "INJECT",
    "PATH",
    "REQUEST",
    "CompiledRoute",
    "CorrelationIdMiddleware",
    "ErrorMappingMiddleware",
    "HandlerParameter",
    "HttpAdapter",
    "RequestScopeMiddleware",
    "build_endpoint",
    "compile_route",
    "error_payload",
    "internal_error_payload",
    "read_json_object",
]
