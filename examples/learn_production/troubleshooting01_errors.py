"""Walkthrough — the failures a deployment sees, named, and the one line that identifies each.

Run it with:

    python -m learn_production.troubleshooting01_errors
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from xyberos import App, Inject, Scope
from xyberos.errors import XyberosError


class Clock:
    """A contract with no provider, so the graph cannot be satisfied."""


class Tick:
    """A contract used to build a cycle."""

    def __init__(self, tock: Annotated[Tock, Inject()]) -> None:  # noqa: F821
        self.tock = tock


class Tock:
    """The other half of that cycle."""

    def __init__(self, tick: Annotated[Tick, Inject()]) -> None:
        self.tick = tick


class Counter:
    """A request-scoped contract, so a longer-lived service must not depend on it."""


class Reporter:
    """An application-scoped service that reaches for a request-scoped one."""

    def __init__(self, counter: Annotated[Counter, Inject()]) -> None:
        self.counter = counter


class Handle:
    """A resource the container is expected to close, which is what transient scope forbids."""

    async def aclose(self) -> None:
        """Nothing to release; the presence of this method is the point."""


class Broken:
    """A resource whose shutdown fails, so the failure is reportable rather than fatal."""

    async def aclose(self) -> None:
        """Fail the way a socket that is already gone does."""
        raise OSError("connection reset by peer")


def report(label: str, action: object) -> None:
    """Print what a failure is called and what it says."""
    try:
        action()  # type: ignore[operator]
    except XyberosError as error:
        print(f"{label}: {type(error).__name__}: {error}")


async def areport(label: str, awaitable: object) -> None:
    """The same, for the failures only an awaitable can raise."""
    try:
        await awaitable  # type: ignore[misc]
    except XyberosError as error:
        print(f"{label}: {type(error).__name__}: {error}")


async def scenario() -> None:
    """Trigger each failure by doing the thing that causes it."""
    # A registration whose factory cannot produce the contract it claims. The class is checked at
    # registration time, so a mistake here never reaches a request.
    report("factory returns the wrong type", lambda: App().provide(Clock, Counter))

    # A dependency with no provider: reported when the graph is validated, naming the path.
    graph = App()
    graph.provide(Tick)
    report("missing provider", graph.validate)

    # A cycle: the same validation, with the path that closes the loop.
    cyclic = App()
    cyclic.provide(Tick)
    cyclic.provide(Tock)
    report("dependency cycle", cyclic.validate)

    # A scope violation: an app-scoped service outliving a request-scoped dependency.
    scoped = App()
    scoped.provide(Counter, scope=Scope.REQUEST)
    scoped.provide(Reporter)
    report("scope violation", scoped.validate)

    # Request scope resolved outside a request: legal to register, illegal to resolve.
    outside = App()
    outside.provide(Counter, scope=Scope.REQUEST)
    async with outside.lifespan():
        await areport("request scope with no request", outside.resolve(Counter))

    # A transient provider returning something the container would have to close. Transient
    # instances are never tracked, so this is refused rather than leaked.
    transient = App()
    transient.provide(Handle, scope=Scope.TRANSIENT)
    async with transient.lifespan():
        await areport("transient managed resource", transient.resolve(Handle))

    # Registration and startup are one-way transitions.
    sealed = App()
    async with sealed.lifespan():
        report("register after start", lambda: sealed.provide(Clock, Counter))
    await areport("start after stop", sealed.start())

    # Shutdown failures are collected after every resource has been closed, so one broken resource
    # never hides the rest, and `.resources` names them. The close hook is found by name, which is
    # why this resource needs no registration ceremony beyond existing.
    closing = App()
    closing.provide(Broken)
    try:
        async with closing.lifespan():
            await closing.resolve(Broken)
    except XyberosError as error:
        print(f"failed shutdown: {type(error).__name__}: {error}")
        print("resources that failed:", getattr(error, "resources", ()))


def main() -> None:
    """Run the scenario."""
    asyncio.run(scenario())


if __name__ == "__main__":
    main()
