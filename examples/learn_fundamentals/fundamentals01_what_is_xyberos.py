"""Lesson 1 — what Xyberos is.

The smallest useful program: compose an application, register one service, run it for the duration
of a context manager, and ask for the service. Every name below is a documented import from the
stable surface, and nothing here needs an optional extra installed.
"""

from __future__ import annotations

import asyncio

import xyberos
from xyberos import App, Scope


class Greeter:
    """A service: an ordinary class that knows nothing about the runtime."""

    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        return f"hello from {self.name}"


async def main() -> None:
    """Print what the runtime is made of, using only the stable surface."""
    app = App()
    app.provide(Greeter, instance=Greeter("Xyberos"))

    print(f"xyberos {xyberos.__version__}")
    print(f"scopes: {', '.join(scope.value for scope in Scope)}")
    print(f"before start: {app.state.value}")

    async with app.lifespan():
        print(f"running: {app.state.value}")
        greeter = await app.resolve(Greeter)
        print(greeter.greet())
        print(f"providers: {len(app.diagnostics().providers)}")
        print(f"registered by: {app.diagnostics().providers[0].source}")

    print(f"after stop: {app.state.value}")


if __name__ == "__main__":
    asyncio.run(main())
