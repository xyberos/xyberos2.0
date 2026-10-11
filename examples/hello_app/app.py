"""The smallest complete Xyberos application: one service, two routes, one config file.

Run it with:

    python -m pip install -e ".[http]" uvicorn
    uvicorn --app-dir examples/hello_app app:asgi_app

Every piece here shows one idea and nothing more: the service holds no HTTP types, the handlers
declare what they need instead of looking it up, the application name comes from the
``xyberos.toml`` next to this file, and the route records stay in core while Starlette stays
behind the adapter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from starlette.applications import Starlette
from starlette.requests import Request

from xyberos import App, Inject, Scope, Settings
from xyberos.http import HttpAdapter

CONFIG_DIRECTORY = Path(__file__).parent


class Greeter:
    """The application's one capability, built once and shared by every request.

    A plain class with no framework types: it is app-scoped because nothing about a greeting
    belongs to a single request, and it is closed by ``App.stop()`` because it defines ``aclose``.
    """

    def __init__(self, app_name: str) -> None:
        self._app_name = app_name

    def greet(self, name: str) -> str:
        """Return the greeting line for ``name``."""
        return f"{self._app_name} says hello, {name}"

    async def aclose(self) -> None:
        """Release what the service owns, if anything.

        Nothing is owned here. The method is present so the example shows where a real service
        would put its cleanup rather than leaving the reader to guess.
        """


class GreetingLog:
    """A request-scoped service: one instance per request, discarded when the request ends.

    The scope is the point. It may depend on an app-scoped service, and the reverse is refused at
    validation time, so a per-request object can never be captured by a long-lived one.
    """

    def __init__(self, greeter: Annotated[Greeter, Inject()]) -> None:
        self._greeter = greeter
        self._names: list[str] = []

    def greet(self, name: str) -> str:
        """Greet ``name`` and remember that this request asked for it."""
        self._names.append(name)
        return self._greeter.greet(name)

    def description(self) -> str:
        """Describe what this request did, which is only ever this request's business."""
        return ", ".join(self._names)


def create_app(settings: Settings | None = None) -> App:
    """Compose the application.

    Settings are read from this example's own directory rather than the working directory, so the
    example behaves the same however it is launched.
    """
    resolved = settings if settings is not None else Settings.load(cwd=CONFIG_DIRECTORY)
    app = App(settings=resolved)
    app.provide(Greeter, instance=Greeter(resolved.app.name))
    app.provide(GreetingLog, scope=Scope.REQUEST)

    @app.get("/")
    async def greet(request: Request, log: Annotated[GreetingLog, Inject()]) -> dict[str, str]:
        """Answer ``/`` with a greeting.

        A handler is a thin translation layer: it declares the services it needs, the runtime
        supplies them inside the request scope that owns their lifetime, and the response is
        converted by the adapter.
        """
        name = request.query_params.get("name", "world")
        return {
            "greeting": log.greet(name),
            "greeted": log.description(),
            "correlation_id": request.headers.get("X-Request-ID", ""),
        }

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Report that the application started and is accepting requests."""
        return {"status": "ok"}

    return app


def build_asgi_app(app: App) -> Starlette:
    """Build the ASGI application that the runtime runs inside."""
    return HttpAdapter(app).asgi_app


asgi_app = build_asgi_app(create_app())
"""The ASGI application an ASGI server imports, as in the command at the top of this module."""
