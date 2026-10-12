"""Walkthrough — the provider registry: what a registration says, and when it is resolved.

Run it with:

    python -m learn_extend.registry01_providers
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from xyberos import App, Inject, Scope, Settings
from xyberos.errors import DependencyCycleError, MissingProviderError


class Clock:
    """An app-scoped capability: one instance, shared by everything that asks for it."""

    def now(self) -> str:
        return "2026-10-12T00:00:00+00:00"


class AuditTrail:
    """A capability whose dependency is declared in its own constructor.

    No factory argument and no manual wiring: the registry reads the annotation at registration time
    and builds the graph, which is also when a missing dependency or a cycle is refused.
    """

    def __init__(self, clock: Annotated[Clock, Inject()]) -> None:
        self._clock = clock
        self.events: list[str] = []

    def record(self, event: str) -> None:
        self.events.append(f"{self._clock.now()} {event}")


class RequestId:
    """A request-scoped capability: one per request context, closed with it."""

    created: int = 0

    def __init__(self) -> None:
        RequestId.created += 1
        self.number = RequestId.created


class First:
    """One half of a dependency cycle, which validation refuses before anything runs."""

    def __init__(self, other: Annotated[Second, Inject()]) -> None: ...


class Second:
    """The other half of the cycle."""

    def __init__(self, first: Annotated[First, Inject()]) -> None:
        self._first = first


async def main() -> None:
    """Register three shapes, read the graph, and watch the two refusals."""
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "registry"}}))
    app.provide(Clock, instance=Clock())
    app.provide(AuditTrail)
    app.provide(RequestId, scope=Scope.REQUEST)

    print(app.diagnostics().render().strip())

    async with app.lifespan():
        audit = await app.resolve(AuditTrail)
        audit.record("started")
        print("an app-scoped instance is shared:", audit is await app.resolve(AuditTrail))
        print("its dependency was injected:", audit.events)

        async with app.request_context() as request:
            one = await request.resolve(RequestId)
            two = await request.resolve(RequestId)
            print("one request context, one instance:", one is two)
        async with app.request_context() as request:
            print(
                "a new request context is a new instance:",
                (await request.resolve(RequestId)) is not one,
            )

        try:
            await app.resolve(str)
        except MissingProviderError as error:
            print("an unregistered contract:", error)

    cyclic = App()
    cyclic.provide(First)
    cyclic.provide(Second)
    try:
        cyclic.validate()
    except DependencyCycleError as error:
        print("a cycle is refused at validation:", error)


if __name__ == "__main__":
    asyncio.run(main())
