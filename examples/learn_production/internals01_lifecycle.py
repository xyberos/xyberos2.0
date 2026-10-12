"""Walkthrough — the lifecycle as a state machine, observed from inside it.

Run it with:

    python -m learn_production.internals01_lifecycle
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from xyberos import App


class Recorder:
    """A resource that records the lifecycle state it saw, at both ends of its life.

    The states are read from inside a provider factory and inside a close hook, which are the only
    two places a caller can observe ``starting`` and ``stopping``: both are transient states that no
    caller of ``start()`` or ``stop()`` ever sees from the outside.
    """

    def __init__(self, name: str, app: App, events: list[str]) -> None:
        self._name = name
        self._app = app
        self._events = events
        self._events.append(f"{name} created while {app.state.value}")

    async def aclose(self) -> None:
        """Record the close, and with it the state a shutdown hook runs in."""
        self._events.append(f"{self._name} closed while {self._app.state.value}")


class First(Recorder):
    """The first registered resource, so that closing order has something to reverse."""


class Second(Recorder):
    """The second registered resource, and therefore the first to be closed."""


class Extra:
    """A contract registered after validation, to show what that does to the state machine."""

    marker: ClassVar[str] = "registered late"


async def scenario() -> None:
    """Walk the application through its states, printing each one as it is reached."""
    app = App()
    events: list[str] = []

    print("after construction:", app.state.value)

    app.provide(First, lambda: First("first", app, events), eager=True)
    app.provide(Second, lambda: Second("second", app, events), eager=True)
    print("after registering:", app.state.value)

    plan = app.validate()
    print("after validate:", app.state.value)
    names = [
        getattr(provider.contract, "__qualname__", repr(provider.contract)) for provider in plan
    ]
    print("dependency-safe order:", names)

    # Registration is what the validated plan is a statement about, so registering invalidates it
    # rather than leaving a stale plan behind. Startup revalidates.
    app.provide(Extra, instance=Extra())
    print("after registering late:", app.state.value)

    await app.start()
    print("after start:", app.state.value)

    # Starting an application that is already ready is a no-op, and so is stopping one that is
    # already stopped: both are safe to call from a shutdown hook that may run twice.
    await app.start()
    print("after starting twice:", app.state.value)

    await app.stop()
    print("after stop:", app.state.value)

    await app.stop()
    print("after stopping twice:", app.state.value)

    print("what the resources saw, in order:")
    for index, event in enumerate(events, start=1):
        print(f"  {index}. {event}")


def main() -> None:
    """Run the scenario."""
    asyncio.run(scenario())


if __name__ == "__main__":
    main()
