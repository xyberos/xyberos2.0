"""A custom plugin example: contribute a service, a route, and configuration.

The plugin in this file is application-local. A real third-party plugin is packaged the same way
but shipped separately, as `tests/fixtures/metrics_plugin` demonstrates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from starlette.applications import Starlette

from xyberos import App, Inject, Plugin, Settings
from xyberos.http import HttpAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class GreetingConfig:
    """Typed configuration for :class:`GreetingPlugin`."""

    greeting: str = "hello"
    excited: bool = False


class Greeter:
    """The capability the plugin contributes."""

    def __init__(self, config: GreetingConfig) -> None:
        self._config = config

    def greet(self, name: str) -> str:
        """Return a greeting, honouring the configured style."""
        message = f"{self._config.greeting}, {name}"
        return f"{message}!" if self._config.excited else message


class GreetingPlugin(Plugin[GreetingConfig]):
    """Contributes the :class:`Greeter` service and a ``/greet`` route."""

    name = "greeting"
    api_version = "1"
    config_type = GreetingConfig

    def __init__(self) -> None:
        self.started = False

    def register(self, app: App, config: GreetingConfig) -> None:
        app.provide(Greeter, instance=Greeter(config))
        app.get("/greet")(self._greet)

    async def _greet(self, greeter: Annotated[Greeter, Inject()]) -> dict[str, str]:
        return {"message": greeter.greet("world")}

    async def start(self) -> None:
        # A real plugin would prepare its own resources here; providers are already constructed.
        self.started = True

    async def stop(self) -> None:
        self.started = False


def create_app(config: Mapping[str, object] | None = None) -> App:
    """Compose an application with the greeting plugin registered.

    Plugin settings are read from ``[plugins.greeting]``, from ``XYBEROS_PLUGINS__GREETING__*``
    environment variables, or from the explicit mapping, in that order of precedence.
    """
    app = App(settings=Settings.load(overrides={"app": {"name": "custom_plugin"}}))
    app.add_plugin(GreetingPlugin(), config=config)
    return app


def build_asgi_app(app: App) -> Starlette:
    """Build an ASGI application for a composed example application."""
    return HttpAdapter(app).asgi_app


def app_factory() -> Starlette:
    """Create the example ASGI application for an ASGI server.

    Usage: ``uvicorn --app-dir examples/custom_plugin --factory app:app_factory``
    """
    return build_asgi_app(create_app())
