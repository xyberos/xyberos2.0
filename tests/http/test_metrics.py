"""Request counters: per route, per status, and nothing behind the application's back.

The middleware sits in the application middleware slot, which is inside the adapter's error mapping,
so the tests that matter most are the ones about which status a failure is counted at and about the
route *template* being the key rather than the raw path.
"""

from __future__ import annotations

import pytest
from starlette.middleware import Middleware

from xyberos import App, HttpError
from xyberos.errors import ConfigurationError
from xyberos.http import (
    OTHER_ROUTE,
    UNMATCHED_ROUTE,
    HttpAdapter,
    RequestCount,
    RequestMetrics,
    RequestMetricsMiddleware,
)
from xyberos.http.testing import create_test_client


class NotFound(HttpError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no such thing: {name}", status_code=404)


def build_app() -> App:
    app = App()

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/users/{user_id}")
    async def user(user_id: int) -> dict[str, int]:
        return {"user_id": user_id}

    @app.get("/missing")
    async def missing() -> dict[str, str]:
        raise NotFound("thing")

    return app


def counted_client(metrics: RequestMetrics):
    middleware = (Middleware(RequestMetricsMiddleware, metrics=metrics),)
    return create_test_client(HttpAdapter(build_app(), middleware=middleware))


def test_the_readout_counts_each_route_and_status() -> None:
    metrics = RequestMetrics()

    with counted_client(metrics) as client:
        assert client.get("/ok").status_code == 200
        assert client.get("/ok").status_code == 200
        assert client.get("/missing").status_code == 404

    assert metrics.count_for("/ok", 200) == 2
    assert metrics.count_for("/missing", 404) == 1
    assert metrics.snapshot() == (
        RequestCount(route="/missing", status=404, count=1),
        RequestCount(route="/ok", status=200, count=2),
    )


def test_a_declared_error_is_counted_at_the_status_the_client_receives() -> None:
    """A 404 raised by a handler is a 404, not the 500 a middleware without the error cannot see."""

    metrics = RequestMetrics()

    with counted_client(metrics) as client:
        assert client.get("/missing").status_code == 404

    assert metrics.count_for("/missing", 404) == 1
    assert metrics.count_for("/missing", 500) == 0


def test_a_path_parameter_is_counted_as_its_route_template() -> None:
    metrics = RequestMetrics()

    with counted_client(metrics) as client:
        client.get("/users/1")
        client.get("/users/2")
        client.get("/users/3")

    assert metrics.count_for("/users/{user_id}", 200) == 3
    assert [row.route for row in metrics.snapshot()] == ["/users/{user_id}"]


def test_a_request_that_matches_no_route_is_counted_under_one_name() -> None:
    metrics = RequestMetrics()

    with counted_client(metrics) as client:
        assert client.get("/no-such-route").status_code == 404
        assert client.get("/another-missing-path").status_code == 404

    assert metrics.count_for(UNMATCHED_ROUTE, 404) == 2
    assert [row.route for row in metrics.snapshot()] == [UNMATCHED_ROUTE]


def test_the_route_ceiling_folds_the_rest_together() -> None:
    metrics = RequestMetrics(max_routes=2)

    metrics.record("/a", 200)
    metrics.record("/b", 200)
    metrics.record("/c", 200)
    metrics.record("/c", 200)

    assert metrics.count_for("/a", 200) == 1
    assert metrics.count_for("/b", 200) == 1
    assert metrics.count_for("/c", 200) == 0
    assert metrics.count_for(OTHER_ROUTE, 200) == 2
    assert len({row.route for row in metrics.snapshot()}) == 3


def test_the_ceiling_must_be_usable() -> None:
    with pytest.raises(ConfigurationError, match="at least 1"):
        RequestMetrics(max_routes=0)


def test_nothing_is_counted_when_the_application_does_not_pass_the_middleware() -> None:
    metrics = RequestMetrics()

    with create_test_client(HttpAdapter(build_app())) as client:
        assert client.get("/ok").status_code == 200

    assert metrics.snapshot() == ()


def test_two_applications_count_separately() -> None:
    first = RequestMetrics()
    second = RequestMetrics()

    with counted_client(first) as client:
        client.get("/ok")
    with counted_client(second) as client:
        client.get("/ok")
        client.get("/ok")

    assert first.count_for("/ok", 200) == 1
    assert second.count_for("/ok", 200) == 2
