"""The adapter coordinates lifespan, injection, middleware order, and error normalization."""

from typing import Annotated

import pytest
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from xyberos import (
    App,
    HttpError,
    Inject,
    LifecycleState,
    RequestValidationError,
    RouteRegistrationError,
    Settings,
)
from xyberos import (
    Scope as DependencyScope,
)
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client
from xyberos.runtime.context import get_correlation_id


class Recorder:
    def __init__(self) -> None:
        self.closed: list[str] = []
        self._resource_count = 0

    def next_resource_number(self) -> int:
        self._resource_count += 1
        return self._resource_count


class AppResource:
    def __init__(self, recorder: Annotated[Recorder, Inject()]) -> None:
        self._recorder = recorder

    async def aclose(self) -> None:
        self._recorder.closed.append("app")


class RequestResource:
    def __init__(self, recorder: Annotated[Recorder, Inject()]) -> None:
        self._recorder = recorder
        self.number = recorder.next_resource_number()

    async def aclose(self) -> None:
        self._recorder.closed.append(f"request:{self.number}")


class Service:
    def __init__(self) -> None:
        self.calls = 0


class NotFoundError(HttpError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is missing", status_code=404)


def build_app(recorder: Recorder) -> App:
    app = App(settings=Settings.load(environ={}))
    app.provide(Recorder, instance=recorder)
    app.provide(Service)
    app.provide(AppResource, eager=True)
    app.provide(RequestResource, scope=DependencyScope.REQUEST)

    @app.get("/service")
    async def service(service: Annotated[Service, Inject()]) -> dict[str, int]:
        service.calls += 1
        return {"calls": service.calls}

    @app.get("/resource")
    async def resource(resource: Annotated[RequestResource, Inject()]) -> dict[str, int]:
        return {"resource": resource.number}

    @app.get("/text")
    async def text() -> PlainTextResponse:
        return PlainTextResponse("plain")

    @app.get("/empty")
    async def empty() -> None:
        return None

    @app.get("/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/missing")
    async def missing() -> dict[str, str]:
        raise NotFoundError("thing")

    @app.get("/invalid")
    async def invalid() -> dict[str, str]:
        raise RequestValidationError("bad input", errors=["name"])

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("internal secret")

    return app


def test_requests_are_rejected_before_the_lifespan_starts() -> None:
    app = build_app(Recorder())

    client = create_test_client(HttpAdapter(app))
    response = client.get("/service")
    client.close()

    assert response.status_code == 500
    assert app.state is LifecycleState.NEW


def test_the_client_starts_the_runtime_and_shutdown_releases_resources() -> None:
    recorder = Recorder()
    app = build_app(recorder)
    adapter = HttpAdapter(app)

    with create_test_client(adapter) as client:
        assert app.state is LifecycleState.READY
        assert client.get("/service").status_code == 200

    assert app.state is LifecycleState.STOPPED
    assert "app" in recorder.closed


def test_injected_app_services_are_shared_across_requests() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/service").json() == {"calls": 1}
        assert client.get("/service").json() == {"calls": 2}


def test_request_scoped_resources_are_closed_after_each_request() -> None:
    recorder = Recorder()
    app = build_app(recorder)

    with create_test_client(HttpAdapter(app)) as client:
        first = client.get("/resource").json()["resource"]
        second = client.get("/resource").json()["resource"]
        closed_by_requests = list(recorder.closed)

    assert first != second
    assert closed_by_requests == [f"request:{first}", f"request:{second}"]
    assert recorder.closed == [f"request:{first}", f"request:{second}", "app"]


def test_response_conversions() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        text = client.get("/text")
        empty = client.get("/empty")

    assert text.status_code == 200
    assert text.text == "plain"
    assert empty.status_code == 204


def test_path_parameters_are_converted_and_validated() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/items/7").json() == {"item_id": 7}
        invalid = client.get("/items/seven")

    assert invalid.status_code == 422
    assert invalid.json()["error"]["type"] == "RequestValidationError"


def test_application_errors_use_their_declared_status() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"error": {"type": "NotFoundError", "message": "thing is missing"}}


def test_validation_errors_expose_their_details() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        response = client.get("/invalid")

    assert response.status_code == 422
    assert response.json()["error"]["errors"] == ["name"]


def test_unexpected_errors_are_internal_and_do_not_leak_details() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert "internal secret" not in response.text
    assert response.json()["error"]["type"] == "InternalServerError"


def test_correlation_ids_are_generated_and_echoed() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        generated = client.get("/service")
        supplied = client.get("/service", headers={"X-Request-ID": "known-id"})

    assert generated.headers["X-Request-ID"]
    assert supplied.headers["X-Request-ID"] == "known-id"


def test_error_responses_keep_the_correlation_id() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        response = client.get("/boom", headers={"X-Request-ID": "trace-me"})

    assert response.headers["X-Request-ID"] == "trace-me"


def test_middleware_runs_outer_to_inner_in_the_documented_order() -> None:
    recorder = Recorder()
    app = build_app(recorder)
    events: list[tuple[str, bool, int]] = []

    @app.get("/order")
    async def order(resource: Annotated[RequestResource, Inject()]) -> dict[str, int]:
        events.append(("endpoint", get_correlation_id() is not None, resource.number))
        return {"resource": resource.number}

    class RecorderMiddleware:
        def __init__(self, app: object) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http":
                resource = await app.resolve(RequestResource)
                events.append(("user", get_correlation_id() is not None, resource.number))
            await self.app(scope, receive, send)  # type: ignore[operator]

    adapter = HttpAdapter(app, middleware=[Middleware(RecorderMiddleware)])

    with create_test_client(adapter) as client:
        response = client.get("/order")

    assert response.status_code == 200
    assert len(events) == 2
    assert events[0][0] == "user"
    assert events[1][0] == "endpoint"
    assert events[0][1] is True
    assert events[0][2] == events[1][2]
    assert response.json()["resource"] == events[1][2]


def test_unsupported_handler_parameters_fail_when_the_adapter_is_created() -> None:
    app = App(settings=Settings.load(environ={}))

    @app.get("/items")
    async def items(limit: int) -> list[str]:
        return []

    with pytest.raises(RouteRegistrationError):
        HttpAdapter(app)


def test_the_adapter_rebuilds_when_routes_change() -> None:
    app = build_app(Recorder())
    adapter = HttpAdapter(app)

    @app.get("/late")
    async def late() -> dict[str, bool]:
        return {"late": True}

    with create_test_client(adapter) as client:
        assert client.get("/late").json() == {"late": True}


def test_unrouted_paths_and_methods_are_reported() -> None:
    app = build_app(Recorder())

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/nope").status_code == 404
        assert client.post("/service").status_code == 405
