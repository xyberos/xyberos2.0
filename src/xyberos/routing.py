"""Dependency-free route records and registration.

Route registration stays in the runtime so that ``App`` can offer decorators without importing
an HTTP library. An adapter (``xyberos.http``) compiles these records into real routes and owns
handler signature validation, request/response types, and ASGI behavior.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from xyberos.errors import RouteRegistrationError

Handler: TypeAlias = Callable[..., object]
SUPPORTED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_PATH_PARAMETER = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")


@dataclass(frozen=True)
class Route:
    """An immutable route record that is independent of any HTTP framework."""

    method: str
    path: str
    handler: Handler
    name: str

    @property
    def path_parameters(self) -> tuple[str, ...]:
        """Return the parameter names declared in the path template, in order."""
        return tuple(_PATH_PARAMETER.findall(self.path))


class RouteRegistry:
    """An application-local set of route records that can be compiled by an adapter."""

    def __init__(self) -> None:
        self._routes: list[Route] = []
        self._version = 0

    @property
    def version(self) -> int:
        """A monotonic counter that lets adapters detect new registrations."""
        return self._version

    @property
    def routes(self) -> tuple[Route, ...]:
        """Return the registered routes in registration order."""
        return tuple(self._routes)

    def add(
        self,
        method: str,
        path: str,
        handler: Handler,
        *,
        name: str | None = None,
    ) -> Route:
        """Register one route and reject ambiguous or malformed registrations."""
        normalized = method.upper()
        if normalized not in SUPPORTED_METHODS:
            supported = ", ".join(sorted(SUPPORTED_METHODS))
            raise RouteRegistrationError(
                f"unsupported HTTP method {method!r}; expected one of: {supported}"
            )
        _ensure_well_formed_path(path)
        if not callable(handler):
            raise RouteRegistrationError(f"the handler for {normalized} {path} must be callable")
        route_name = name or getattr(handler, "__name__", "")
        if not route_name:
            raise RouteRegistrationError(f"the route {normalized} {path} needs an explicit name")
        if any(route.method == normalized and route.path == path for route in self._routes):
            raise RouteRegistrationError(f"a route is already registered for {normalized} {path}")
        if any(route.name == route_name for route in self._routes):
            raise RouteRegistrationError(f"a route named {route_name!r} is already registered")
        route = Route(method=normalized, path=path, handler=handler, name=route_name)
        self._routes.append(route)
        self._version += 1
        return route

    def clone(self) -> RouteRegistry:
        """Return an independent copy for an isolated application or test override."""
        clone = RouteRegistry()
        clone._routes = list(self._routes)
        clone._version = self._version
        return clone


def _ensure_well_formed_path(path: str) -> None:
    if not path.startswith("/"):
        raise RouteRegistrationError(f"route path must start with '/': {path!r}")
    remainder = _PATH_PARAMETER.sub("", path)
    if "{" in remainder or "}" in remainder:
        raise RouteRegistrationError(f"route path has an unbalanced parameter: {path!r}")
