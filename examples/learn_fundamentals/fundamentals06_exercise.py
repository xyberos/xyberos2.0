"""Lesson 6, exercise — the same application without the failing provider.

The answer to the lesson's exercise, kept as a file so the output the page claims is the output this
module really produces. The only difference from the lesson is which provider was removed.
"""

from __future__ import annotations

import asyncio

from xyberos import App


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
    """Run the exercise's version of lesson 6."""
    app = App()
    app.provide(Connection, factory=connection_factory, eager=True)

    print("initial:", app.state.value)
    await app.start()
    print("after start:", app.state.value)
    await app.stop()
    print("after stop:", app.state.value)


if __name__ == "__main__":
    asyncio.run(main())
