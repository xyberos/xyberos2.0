"""Lesson 6 — what happens between start and stop.

A failing eager provider is the interesting case: the application does not end up half-started. What
was already constructed is closed, the state becomes ``failed``, and ``stop()`` still returns the
application to ``stopped``. ``failed`` is a state you can leave, which is what makes it a state
rather than an exit.
"""

from __future__ import annotations

import asyncio

from xyberos import App
from xyberos.errors import DependencyResolutionError


class BrokenService:
    """A service that cannot be constructed, so startup has to unwind."""

    def __init__(self) -> None:
        raise RuntimeError("the service could not be built")


class Connection:
    """A service that owns a resource, so the runtime is responsible for closing it."""

    async def aclose(self) -> None:
        """Release the resource."""
        print("connection released")


async def connection_factory() -> Connection:
    """Build the connection that the application will own."""
    print("connection acquired")
    return Connection()


async def main() -> None:
    """Watch a failed startup clean up after itself."""
    app = App()
    app.provide(Connection, factory=connection_factory, eager=True)
    app.provide(BrokenService, eager=True)

    print("initial:", app.state.value)
    try:
        await app.start()
    except DependencyResolutionError as error:
        print("startup failed:", error)
    print("after the failure:", app.state.value)

    await app.stop()
    print("after stop:", app.state.value)


if __name__ == "__main__":
    asyncio.run(main())
