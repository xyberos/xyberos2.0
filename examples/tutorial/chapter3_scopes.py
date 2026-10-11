"""Chapter 3 — how long a service lives.

Run it with:

    python examples/tutorial/chapter3_scopes.py
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from xyberos import App, Inject, Scope


class Cache:
    """App-scoped: one instance for the whole application."""


class RequestState:
    """Request-scoped: one instance per request, discarded with it."""

    def __init__(self, cache: Annotated[Cache, Inject()]) -> None:
        self.cache = cache


class Formatter:
    """Transient: a new instance every time it is resolved."""


async def main() -> None:
    app = App()
    app.provide(Cache)
    app.provide(RequestState, scope=Scope.REQUEST)
    app.provide(Formatter, scope=Scope.TRANSIENT)

    async with app.lifespan():
        print(
            "app-scoped gives the same instance:",
            await app.resolve(Cache) is await app.resolve(Cache),
        )
        print(
            "transient gives a new instance:",
            await app.resolve(Formatter) is await app.resolve(Formatter),
        )

        async with app.request_context() as request:
            first = await request.resolve(RequestState)
            second = await request.resolve(RequestState)
            print("request-scoped is stable inside one request:", first is second)

        async with app.request_context() as request:
            third = await request.resolve(RequestState)
            print("request-scoped is new in the next request:", third is not first)


if __name__ == "__main__":
    asyncio.run(main())
