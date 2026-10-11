"""Handler signatures are validated before any request is served."""

from typing import Annotated

import pytest
from starlette.requests import Request

from xyberos import Inject, Route, RouteRegistrationError
from xyberos.http.routing import INJECT, PATH, REQUEST, compile_route


class Service:
    pass


def make_route(path: str, handler: object) -> Route:
    return Route(method="GET", path=path, handler=handler, name="route")  # type: ignore[arg-type]


def test_injected_dependencies_reuse_the_runtime_marker() -> None:
    async def handler(service: Annotated[Service, Inject()]) -> None:
        return None

    compiled = compile_route(make_route("/probe", handler))

    assert [(parameter.name, parameter.kind) for parameter in compiled.parameters] == [
        ("service", INJECT)
    ]
    assert compiled.parameters[0].contract is Service


def test_injected_contracts_can_use_an_opaque_key() -> None:
    async def handler(value: Annotated[str, Inject(contract="greeting")]) -> None:
        return None

    compiled = compile_route(make_route("/probe", handler))

    assert compiled.parameters[0].contract == "greeting"


def test_path_parameters_support_str_and_int() -> None:
    async def handler(item_id: int, slug: str, request: Request) -> None:
        return None

    compiled = compile_route(make_route("/items/{item_id}/{slug}", handler))

    kinds = {parameter.name: parameter.kind for parameter in compiled.parameters}
    assert kinds == {"item_id": PATH, "slug": PATH, "request": REQUEST}
    assert compiled.parameters[0].converter is int


def test_unclassified_parameters_are_rejected() -> None:
    async def handler(limit: int) -> None:
        return None

    with pytest.raises(RouteRegistrationError) as info:
        compile_route(make_route("/items", handler))

    assert "must be an injected dependency" in str(info.value)


def test_variadic_parameters_are_rejected() -> None:
    async def handler(**kwargs: object) -> None:
        return None

    with pytest.raises(RouteRegistrationError):
        compile_route(make_route("/items", handler))


def test_path_parameters_missing_from_the_signature_are_rejected() -> None:
    async def handler() -> None:
        return None

    with pytest.raises(RouteRegistrationError) as info:
        compile_route(make_route("/items/{item_id}", handler))

    assert "missing from the handler signature" in str(info.value)


def test_unsupported_path_parameter_annotations_are_rejected() -> None:
    async def handler(item_id: float) -> None:
        return None

    with pytest.raises(RouteRegistrationError):
        compile_route(make_route("/items/{item_id}", handler))


def test_unhashable_injected_contracts_are_rejected() -> None:
    async def handler(item: Annotated[str, Inject(contract=["not", "hashable"])]) -> None:
        return None

    with pytest.raises(RouteRegistrationError):
        compile_route(make_route("/items", handler))


def test_uninspectable_handlers_are_reported() -> None:
    with pytest.raises(RouteRegistrationError):
        compile_route(make_route("/items", len))
