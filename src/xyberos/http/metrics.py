"""Request counters, as a middleware the application passes to the adapter.

Xyberos installs no middleware for an application — ``HttpAdapter(app, middleware=(...))`` is the
application's call — so this is a class the composition root passes, and the counters it writes to
are the application's too. There is no sink, exporter, background task, or global: a deployment that
wants these numbers somewhere else reads :meth:`RequestMetrics.snapshot` on a schedule it owns.

The middleware reads the matched route template from the scope, which the adapter's compiled
endpoint records under :data:`~xyberos.http.routing.MATCHED_ROUTE_KEY`. That is why the counters are
per *route* rather than per raw path: a counter keyed by ``/users/1234`` is a memory leak with extra
steps, and :class:`RequestMetrics` bounds the number of distinct routes for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("http", error) from error

from xyberos.errors import ConfigurationError, HttpError
from xyberos.http.routing import MATCHED_ROUTE_KEY

__all__ = [
    "DEFAULT_MAX_ROUTES",
    "OTHER_ROUTE",
    "UNMATCHED_ROUTE",
    "RequestCount",
    "RequestMetrics",
    "RequestMetricsMiddleware",
]

UNMATCHED_ROUTE = "<unmatched>"
"""The key used for a request that never reached a route, such as a path no route matches."""

OTHER_ROUTE = "<other>"
"""The key used once the distinct-route ceiling is reached.

A path no route matched is caller-controlled, so counting each one by name would let a client decide
how much memory the counter map grows to.
"""

DEFAULT_MAX_ROUTES = 200
"""How many distinct routes are counted by name before the rest are folded into ``OTHER_ROUTE``."""

INTERNAL_ERROR_STATUS = 500
"""What a request counts as when it produced no response at all.

The adapter's error mapping sits *outside* application middleware, so this middleware cannot see the
response it sends. A deliberate ``HttpError`` is counted at its own status by catching it on the way
past; anything else reaches a client as a 500, which is what this default records.
"""


@dataclass(frozen=True)
class RequestCount:
    """One counted route and status, as reported by :meth:`RequestMetrics.snapshot`."""

    route: str
    status: int
    count: int


class RequestMetrics:
    """Per-route, per-status counters for one process.

    Counters live in this object and nowhere else. They are per process rather than per host, which
    is what a single-host framework ships: an application served by four workers has four of these,
    and combining them is the deployment's business rather than a hidden aggregation step.
    """

    def __init__(self, *, max_routes: int = DEFAULT_MAX_ROUTES) -> None:
        if max_routes < 1:
            raise ConfigurationError("max_routes must be at least 1")
        self._max_routes = max_routes
        self._counts: dict[tuple[str, int], int] = {}

    @property
    def max_routes(self) -> int:
        """How many distinct routes are counted by name before the rest are folded together."""
        return self._max_routes

    def record(self, route: str, status: int) -> None:
        """Count one request against ``route`` and ``status``."""
        key = (route, status)
        if key not in self._counts and len({name for name, _ in self._counts}) >= self._max_routes:
            key = (OTHER_ROUTE, status)
        self._counts[key] = self._counts.get(key, 0) + 1

    def count_for(self, route: str, status: int) -> int:
        """Return how many requests ``route`` answered with ``status``, or zero."""
        return self._counts.get((route, status), 0)

    def snapshot(self) -> tuple[RequestCount, ...]:
        """Return every counter, ordered by route and then status."""
        return tuple(
            RequestCount(route=route, status=status, count=count)
            for (route, status), count in sorted(self._counts.items())
        )


class RequestMetricsMiddleware:
    """Count one request against the route it matched and the status it received.

    Place it in the application middleware slot — ``HttpAdapter(app, middleware=(Middleware(
    RequestMetricsMiddleware, metrics=metrics),))`` — which is inside the adapter's error mapping.
    That position is what lets a failure be counted at the status the client will receive instead of
    a guessed one.
    """

    def __init__(self, app: ASGIApp, *, metrics: RequestMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = INTERNAL_ERROR_STATUS

        async def track(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, track)
        except HttpError as error:
            status = error.status_code
            raise
        finally:
            self.metrics.record(matched_route(scope), status)


def matched_route(scope: Scope) -> str:
    """Return the template a request matched, or :data:`UNMATCHED_ROUTE` when it matched none."""
    route = scope.get(MATCHED_ROUTE_KEY)
    return route if isinstance(route, str) else UNMATCHED_ROUTE
