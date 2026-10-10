"""Core route records stay dependency-free and reject ambiguous registrations."""

import asyncio

import pytest

from xyberos import App, LifecycleStateError, RouteRegistrationError, Settings


def new_app() -> App:
    return App(settings=Settings.load(environ={}))


def test_registered_routes_are_recorded_in_order() -> None:
    app = new_app()

    @app.get("/items")
    async def list_items() -> list[str]:
        return []

    @app.post("/items")
    async def create_item() -> dict[str, str]:
        return {}

    routes = app.routes

    assert [(route.method, route.path, route.name) for route in routes] == [
        ("GET", "/items", "list_items"),
        ("POST", "/items", "create_item"),
    ]
    assert routes[0].handler is list_items


def test_explicit_route_names_and_versions_are_tracked() -> None:
    app = new_app()
    before = app.route_version

    @app.get("/health", name="health-check")
    async def handler() -> dict[str, str]:
        return {}

    assert app.routes[0].name == "health-check"
    assert app.route_version == before + 1


def test_path_parameters_are_extracted_in_order() -> None:
    app = new_app()

    @app.get("/users/{user_id}/items/{item_id}")
    async def handler() -> None:
        return None

    assert app.routes[0].path_parameters == ("user_id", "item_id")


def test_duplicate_method_and_path_is_rejected() -> None:
    app = new_app()
    app.route("GET", "/items", _noop)

    with pytest.raises(RouteRegistrationError):
        app.route("GET", "/items", _noop)


def test_duplicate_route_name_is_rejected() -> None:
    app = new_app()
    app.route("GET", "/items", _noop, name="items")

    with pytest.raises(RouteRegistrationError):
        app.route("POST", "/items", _noop, name="items")


def test_unsupported_methods_and_paths_are_rejected() -> None:
    app = new_app()

    with pytest.raises(RouteRegistrationError):
        app.route("FETCH", "/items", _noop)
    with pytest.raises(RouteRegistrationError):
        app.route("GET", "items", _noop)
    with pytest.raises(RouteRegistrationError):
        app.route("GET", "/items/{item_id", _noop)
    with pytest.raises(RouteRegistrationError):
        app.route("GET", "/items", "not-callable")  # type: ignore[arg-type]


def test_routes_cannot_be_registered_after_start() -> None:
    async def scenario() -> None:
        app = new_app()
        app.provide(_Resource)
        await app.start()

        with pytest.raises(LifecycleStateError):
            app.route("GET", "/items", _noop)

        await app.stop()

    asyncio.run(scenario())


def test_cloned_app_has_independent_routes() -> None:
    app = new_app()
    app.route("GET", "/items", list_items)

    clone = app.with_overrides({})
    clone.route("GET", "/other", other)

    assert [route.path for route in app.routes] == ["/items"]
    assert [route.path for route in clone.routes] == ["/items", "/other"]


async def list_items() -> None:
    return None


async def other() -> None:
    return None


async def _noop() -> None:
    return None


class _Resource:
    pass
