"""Lifecycle ordering, readiness gating, and cleanup behavior."""

import asyncio
from typing import Annotated

import pytest

from xyberos import (
    App,
    DependencyResolutionError,
    Inject,
    LifecycleState,
    LifecycleStateError,
    MissingProviderError,
    Settings,
    ShutdownError,
)


class EventLog:
    def __init__(self) -> None:
        self.events: list[str] = []

    def add(self, event: str) -> None:
        self.events.append(event)


class FirstResource:
    def __init__(self, log: Annotated[EventLog, Inject()]) -> None:
        self._log = log
        log.add("build:first")

    async def aclose(self) -> None:
        self._log.add("close:first")


class SecondResource:
    def __init__(
        self,
        log: Annotated[EventLog, Inject()],
        first: Annotated[FirstResource, Inject()],
    ) -> None:
        self._log = log
        self._first = first
        log.add("build:second")

    async def aclose(self) -> None:
        self._log.add("close:second")


class ExplodingClose:
    def __init__(self, log: Annotated[EventLog, Inject()]) -> None:
        self._log = log
        log.add("build:exploding")

    async def aclose(self) -> None:
        self._log.add("close:exploding")
        raise RuntimeError("cleanup failed")


class FailingResource:
    def __init__(self, log: Annotated[EventLog, Inject()]) -> None:
        self._log = log
        raise RuntimeError("startup failed")


class IndependentStep:
    name = "step"

    def __init__(self, log: Annotated[EventLog, Inject()]) -> None:
        self._log = log
        log.add(f"build:{type(self).name}")

    async def aclose(self) -> None:
        self._log.add(f"close:{type(self).name}")


class StepAlpha(IndependentStep):
    name = "alpha"


class StepBeta(IndependentStep):
    name = "beta"


class StepGamma(IndependentStep):
    name = "gamma"


INDEPENDENT_STEPS = {"alpha": StepAlpha, "beta": StepBeta, "gamma": StepGamma}


class NoDependency:
    pass


def make_app(log: EventLog) -> App:
    app = App(settings=Settings.load(environ={}))
    app.provide(EventLog, instance=log)
    return app


def test_app_scoped_resources_are_lazy_and_close_in_reverse() -> None:
    async def scenario() -> None:
        log = EventLog()
        app = make_app(log)
        app.provide(FirstResource)
        app.provide(SecondResource)
        await app.start()

        assert log.events == []

        await app.resolve(SecondResource)
        assert log.events == ["build:first", "build:second"]

        await app.stop()
        assert log.events == ["build:first", "build:second", "close:second", "close:first"]

    asyncio.run(scenario())


def test_eager_resources_start_in_dependency_order() -> None:
    async def scenario() -> None:
        log = EventLog()
        app = make_app(log)
        app.provide(FirstResource, eager=True)
        app.provide(SecondResource, eager=True)
        await app.start()

        assert app.state is LifecycleState.READY
        assert log.events == ["build:first", "build:second"]

        await app.stop()
        assert log.events[-2:] == ["close:second", "close:first"]

    asyncio.run(scenario())


def test_explicit_close_hook_is_invoked() -> None:
    async def scenario() -> None:
        log = EventLog()
        app = make_app(log)
        app.provide(NoDependency, close=lambda instance: log.add("close:hook"))
        await app.start()
        await app.resolve(NoDependency)

        await app.stop()

        assert log.events == ["close:hook"]

    asyncio.run(scenario())


def test_partial_startup_failure_closes_started_resources() -> None:
    async def scenario() -> None:
        log = EventLog()
        app = make_app(log)
        app.provide(FirstResource, eager=True)
        app.provide(FailingResource, eager=True)

        with pytest.raises(DependencyResolutionError):
            await app.start()

        assert app.state is LifecycleState.FAILED
        assert log.events == ["build:first", "close:first"]

        with pytest.raises(LifecycleStateError):
            await app.resolve(FirstResource)

        await app.stop()
        assert app.state is LifecycleState.STOPPED

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("plan", "expected"),
    [
        (["boom"], []),
        (["alpha", "boom"], ["build:alpha", "close:alpha"]),
        (
            ["alpha", "beta", "boom"],
            ["build:alpha", "build:beta", "close:beta", "close:alpha"],
        ),
        (
            ["alpha", "beta", "gamma", "boom"],
            [
                "build:alpha",
                "build:beta",
                "build:gamma",
                "close:gamma",
                "close:beta",
                "close:alpha",
            ],
        ),
    ],
)
def test_reverse_cleanup_after_each_startup_failure_point(
    plan: list[str], expected: list[str]
) -> None:
    async def scenario() -> None:
        log = EventLog()
        app = make_app(log)
        for name in plan:
            if name == "boom":
                app.provide(FailingResource, eager=True)
            else:
                app.provide(INDEPENDENT_STEPS[name], eager=True)

        with pytest.raises(DependencyResolutionError):
            await app.start()

        assert app.state is LifecycleState.FAILED
        assert log.events == expected

    asyncio.run(scenario())


def test_shutdown_attempts_every_hook_and_aggregates_failures() -> None:
    async def scenario() -> None:
        log = EventLog()
        app = make_app(log)
        app.provide(FirstResource)
        app.provide(ExplodingClose)
        app.provide(SecondResource)
        await app.start()
        await app.resolve(FirstResource)
        await app.resolve(ExplodingClose)
        await app.resolve(SecondResource)

        with pytest.raises(ShutdownError) as info:
            await app.stop()

        assert app.state is LifecycleState.STOPPED
        assert log.events == [
            "build:first",
            "build:exploding",
            "build:second",
            "close:second",
            "close:exploding",
            "close:first",
        ]
        assert len(info.value.failures) == 1
        assert info.value.resources == ("ExplodingClose",)
        assert isinstance(info.value.failures[0], RuntimeError)

    asyncio.run(scenario())


def test_startup_failure_that_also_fails_cleanup_reports_both() -> None:
    async def scenario() -> None:
        log = EventLog()
        app = make_app(log)
        app.provide(ExplodingClose, eager=True)
        app.provide(FailingResource, eager=True)

        with pytest.raises(ShutdownError) as info:
            await app.start()

        assert app.state is LifecycleState.FAILED
        assert info.value.resources == ("ExplodingClose",)
        assert isinstance(info.value.__cause__, DependencyResolutionError)
        assert log.events == ["build:exploding", "close:exploding"]

    asyncio.run(scenario())


def test_start_validates_the_graph_before_readiness() -> None:
    async def scenario() -> None:
        app = App(settings=Settings.load(environ={}))
        app.provide(SecondResource)

        with pytest.raises(MissingProviderError):
            await app.start()

        assert app.state is LifecycleState.FAILED

    asyncio.run(scenario())


def test_stop_before_start_is_a_no_op() -> None:
    async def scenario() -> None:
        app = App(settings=Settings.load(environ={}))

        await app.stop()

        assert app.state is LifecycleState.STOPPED

    asyncio.run(scenario())


def test_registration_is_rejected_after_start() -> None:
    async def scenario() -> None:
        app = App(settings=Settings.load(environ={}))
        app.provide(NoDependency)
        await app.start()

        with pytest.raises(LifecycleStateError):
            app.provide(NoDependency, replace=True)

        await app.stop()

    asyncio.run(scenario())


def test_lifespan_context_manager_owns_start_and_stop() -> None:
    async def scenario() -> None:
        log = EventLog()
        app = make_app(log)
        app.provide(FirstResource)

        async with app.lifespan() as running:
            assert running is app
            assert app.state is LifecycleState.READY
            await app.resolve(FirstResource)

        assert app.state is LifecycleState.STOPPED
        assert log.events == ["build:first", "close:first"]

    asyncio.run(scenario())
