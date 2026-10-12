"""The internals page's load-bearing claims about shutdown order and lifecycle refusals.

A transcript can show the order two resources were closed in for one run. These tests hold the rules
that make it true for any run: closing is the reverse of construction, a plugin stops before the
resources it registered against, one failing hook does not skip the others, and shutdown drains the
requests that are already in flight.
"""

import asyncio

import pytest

from xyberos import App, Plugin
from xyberos.errors import LifecycleStateError, ShutdownError

EVENTS: list[str] = []


class Resource:
    """A resource that records the order it was constructed and closed in."""

    def __init__(self, name: str) -> None:
        self._name = name
        EVENTS.append(f"created {name}")

    async def aclose(self) -> None:
        EVENTS.append(f"closed {self._name}")


class First(Resource):
    """The first registered resource."""


class Second(Resource):
    """The second registered resource."""


class Broken(Resource):
    """A resource whose close hook fails."""

    async def aclose(self) -> None:
        EVENTS.append(f"closed {self._name}")
        raise OSError("connection reset by peer")


class Recorder(Plugin[None]):
    """A plugin that records its own start and stop, and depends on a provider."""

    name = "recorder"

    def register(self, app: App, config: None) -> None:
        EVENTS.append("registered")

    async def start(self) -> None:
        EVENTS.append("plugin started")

    async def stop(self) -> None:
        EVENTS.append("plugin stopped")


@pytest.fixture(autouse=True)
def _clear_events() -> None:
    EVENTS.clear()


def test_closing_is_the_reverse_of_construction_and_plugins_stop_first() -> None:
    app = App()
    app.add_plugin(Recorder())
    app.provide(First, lambda: First("first"), eager=True)
    app.provide(Second, lambda: Second("second"), eager=True)

    async def scenario() -> None:
        async with app.lifespan():
            pass

    asyncio.run(scenario())

    assert EVENTS == [
        "registered",
        "created first",
        "created second",
        "plugin started",
        "plugin stopped",
        "closed second",
        "closed first",
    ]


def test_one_failing_close_hook_does_not_skip_the_others() -> None:
    app = App()
    app.provide(First, lambda: First("first"), eager=True)
    app.provide(Broken, lambda: Broken("broken"), eager=True)
    app.provide(Second, lambda: Second("second"), eager=True)

    async def scenario() -> None:
        with pytest.raises(ShutdownError) as raised:
            async with app.lifespan():
                pass
        assert raised.value.resources == ("Broken",)
        assert app.state.value == "stopped"

    asyncio.run(scenario())

    assert "closed second" in EVENTS
    assert "closed first" in EVENTS


def test_a_stopped_application_refuses_to_start_and_to_register() -> None:
    app = App()
    app.provide(First, lambda: First("first"))

    async def scenario() -> None:
        async with app.lifespan():
            with pytest.raises(LifecycleStateError, match="ready"):
                app.provide(Second, lambda: Second("second"))
        with pytest.raises(LifecycleStateError, match="stopped"):
            await app.start()

    asyncio.run(scenario())


def test_starting_and_stopping_twice_are_no_ops() -> None:
    app = App()
    app.provide(First, lambda: First("first"), eager=True)

    async def scenario() -> None:
        await app.start()
        await app.start()
        assert app.state.value == "ready"
        await app.stop()
        await app.stop()
        assert app.state.value == "stopped"

    asyncio.run(scenario())

    assert EVENTS == ["created first", "closed first"]


def test_shutdown_waits_for_an_in_flight_request_context() -> None:
    app = App()
    app.provide(First, lambda: First("first"), eager=True)

    async def scenario() -> None:
        await app.start()
        context = app.request_context()
        await context.__aenter__()

        stopping = asyncio.ensure_future(app.stop())
        for _ in range(5):
            await asyncio.sleep(0)
        assert not stopping.done(), "shutdown must not finish while a request is in flight"

        await context.__aexit__(None, None, None)
        await asyncio.wait_for(stopping, timeout=5)
        assert app.state.value == "stopped"

    asyncio.run(scenario())
