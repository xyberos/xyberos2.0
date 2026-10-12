"""Lesson 10 — reading the provider registry.

`app.provide` is the registration, `Inject()` is the resolution, and `app.diagnostics()` is the view
you debug with: every provider, its scope, whether it is eager, and where it came from. Xyberos
reports the source of a provider because "which plugin registered this?" is the first question a
wiring problem asks.
"""

from __future__ import annotations

import asyncio

from xyberos import App, Scope


class Greeter:
    """An ordinary service, registered as a pre-built instance."""

    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        """Return the greeting."""
        return f"hello from {self.name}"


class RequestState:
    """A service whose lifetime is one request."""


async def main() -> None:
    """Register two providers and read the registry's own report."""
    app = App()
    app.provide(Greeter, instance=Greeter("Xyberos"))
    app.provide(RequestState, scope=Scope.REQUEST)
    print(app.diagnostics().render())


if __name__ == "__main__":
    asyncio.run(main())
