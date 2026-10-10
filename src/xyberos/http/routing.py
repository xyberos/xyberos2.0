"""Compile dependency-free route records into Starlette endpoints.

Handler signatures are inspected here, not inside the runtime, because only the HTTP adapter
knows about path parameters and request objects. Every handler parameter must be exactly one of:

* an injected dependency, declared as ``Annotated[T, Inject()]``;
* a path parameter named in the route template (``str`` or ``int``); or
* the Starlette ``Request``.

Anything else fails registration, so ordinary request input never turns into a silent injection.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, TypeAlias, cast, get_args, get_origin, get_type_hints

try:
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("http", error) from error

from xyberos.errors import HttpError, RequestValidationError, RouteRegistrationError
from xyberos.routing import Route
from xyberos.runtime.dependencies import Inject

INJECT = "inject"
PATH = "path"
REQUEST = "request"

_PATH_CONVERTERS: dict[object, Callable[[str], object]] = {str: str, int: int}
Endpoint: TypeAlias = Callable[[Request], Awaitable[Response]]


@dataclass(frozen=True)
class HandlerParameter:
    """One handler parameter and how the adapter supplies it."""

    name: str
    kind: str
    contract: object | None = None
    converter: Callable[[str], object] | None = None


@dataclass(frozen=True)
class CompiledRoute:
    """A route whose handler signature has been validated."""

    route: Route
    parameters: tuple[HandlerParameter, ...]


def compile_route(route: Route) -> CompiledRoute:
    """Validate one handler signature and describe how to call it."""
    where = f"{route.method} {route.path}"
    try:
        signature = inspect.signature(route.handler)
        annotations = get_type_hints(route.handler, include_extras=True)
    except (NameError, TypeError, ValueError) as error:
        raise RouteRegistrationError(f"cannot inspect the handler for {where}") from error

    path_parameters = set(route.path_parameters)
    parameters: list[HandlerParameter] = []
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        if parameter.kind in {parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL}:
            raise RouteRegistrationError(
                f"the handler for {where} cannot declare *args or **kwargs"
            )
        annotation = annotations.get(parameter.name)
        marker = _inject_marker(annotation)
        if marker is not None:
            contract = (
                marker.contract if marker.contract is not None else _annotated_type(annotation)
            )
            if contract is None:
                raise RouteRegistrationError(
                    f"the injected parameter {parameter.name!r} of {where} needs a type contract"
                )
            _ensure_hashable(contract, parameter.name, where)
            parameters.append(HandlerParameter(parameter.name, INJECT, contract=contract))
            continue
        if parameter.name in path_parameters:
            parameters.append(
                HandlerParameter(
                    parameter.name,
                    PATH,
                    converter=_path_converter(annotation, parameter.name, where),
                )
            )
            continue
        if annotation is Request:
            parameters.append(HandlerParameter(parameter.name, REQUEST))
            continue
        raise RouteRegistrationError(
            f"the parameter {parameter.name!r} of {where} must be an injected dependency, a path "
            "parameter, or a Request; read other input from the Request"
        )

    supplied = {parameter.name for parameter in parameters}
    for name in route.path_parameters:
        if name not in supplied:
            raise RouteRegistrationError(
                f"the path parameter {name!r} of {where} is missing from the handler signature"
            )
    return CompiledRoute(route=route, parameters=tuple(parameters))


def build_endpoint(
    compiled: CompiledRoute, resolve: Callable[[object], Awaitable[object]]
) -> Endpoint:
    """Return an endpoint that resolves injected arguments and converts the return value."""

    async def endpoint(request: Request) -> Response:
        arguments: dict[str, object] = {}
        for parameter in compiled.parameters:
            if parameter.kind == INJECT:
                arguments[parameter.name] = await resolve(parameter.contract)
            elif parameter.kind == PATH:
                arguments[parameter.name] = _convert_path_parameter(parameter, request)
            else:
                arguments[parameter.name] = request
        result = compiled.route.handler(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return _as_response(result)

    return endpoint


def _convert_path_parameter(parameter: HandlerParameter, request: Request) -> object:
    raw = request.path_params[parameter.name]
    if parameter.converter is None:
        return raw
    try:
        return parameter.converter(raw)
    except (TypeError, ValueError) as error:
        raise RequestValidationError(
            f"the path parameter {parameter.name!r} is not valid"
        ) from error


def _as_response(result: object) -> Response:
    if isinstance(result, Response):
        return result
    if result is None:
        return Response(status_code=204)
    try:
        return JSONResponse(result)
    except TypeError as error:
        raise HttpError(
            "the route handler returned a value that is not JSON serializable"
        ) from error


def _inject_marker(annotation: object | None) -> Inject | None:
    if get_origin(annotation) is not Annotated:
        return None
    markers = [value for value in get_args(annotation)[1:] if isinstance(value, Inject)]
    return markers[-1] if markers else None


def _annotated_type(annotation: object | None) -> object | None:
    if get_origin(annotation) is not Annotated:
        return None
    return cast(object, get_args(annotation)[0])


def _path_converter(
    annotation: object | None, name: str, where: str
) -> Callable[[str], object] | None:
    if annotation is None:
        return None
    converter = _PATH_CONVERTERS.get(annotation)
    if converter is None:
        raise RouteRegistrationError(
            f"the path parameter {name!r} of {where} must be annotated str or int"
        )
    return converter


def _ensure_hashable(contract: object, name: str, where: str) -> None:
    try:
        hash(contract)
    except TypeError as error:
        raise RouteRegistrationError(
            f"the injected contract of {name!r} in {where} must be hashable"
        ) from error
