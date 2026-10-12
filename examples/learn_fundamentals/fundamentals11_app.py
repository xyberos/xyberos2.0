"""The application lesson 11 inspects, in the shape ``xyberos new`` writes.

A composition root, one service, and two routes — small enough to read, and enough for
``xyberos check`` to have something real to report: the provider graph, the provider sources, and
the handler signatures.
"""

from __future__ import annotations

from typing import Annotated

from xyberos import App, Inject


class Greeter:
    """A service with no HTTP types in it, so it can be tested on its own."""

    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self, who: str) -> str:
        """Return the greeting for ``who``."""
        return f"{self.name} says hello, {who}"


def create_app() -> App:
    """Compose the application ``xyberos check`` is pointed at."""
    app = App()
    app.provide(Greeter, instance=Greeter("Xyberos"))

    @app.get("/")
    async def greet(greeter: Annotated[Greeter, Inject()]) -> dict[str, str]:
        return {"greeting": greeter.greet("world")}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
