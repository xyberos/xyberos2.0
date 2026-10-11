"""Chapter 9 — adding a plugin.

Run it with:

    python examples/tutorial/chapter9_plugins.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from xyberos import App, Inject, Plugin
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


@dataclass(frozen=True)
class CounterConfig:
    """The plugin's own typed configuration."""

    start: int = 0


class Counter:
    """The capability the plugin contributes."""

    def __init__(self, start: int) -> None:
        self._value = start

    def bump(self) -> int:
        """Return the next value."""
        self._value += 1
        return self._value


class CounterPlugin(Plugin[CounterConfig]):
    """Contributes a service and a route, in that order."""

    name = "counter"
    api_version = "1"
    config_type = CounterConfig

    def register(self, app: App, config: CounterConfig) -> None:
        app.provide(Counter, instance=Counter(config.start))

    async def start(self) -> None:
        """Prepare the plugin's own resources, if it has any."""


def create_app(config: dict[str, object] | None = None) -> App:
    """Build an application with the plugin registered."""
    app = App()
    app.add_plugin(CounterPlugin(), config=config)

    @app.get("/count")
    async def count(counter: Annotated[Counter, Inject()]) -> dict[str, int]:
        return {"count": counter.bump()}

    return app


def main() -> None:
    app = create_app({"start": 10})
    with create_test_client(HttpAdapter(app)) as client:
        print(client.get("/count").json())
        print(client.get("/count").json())
        print("--- who provides what ---")
        print(app.diagnostics().render())


if __name__ == "__main__":
    main()
