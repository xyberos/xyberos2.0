"""Isolation between independent applications and test overrides."""

import asyncio
from typing import Annotated

import pytest

from xyberos import App, Inject, LifecycleState, MissingProviderError, Settings


class Repository:
    def __init__(self, name: str = "default") -> None:
        self.name = name
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class Service:
    def __init__(self, repository: Annotated[Repository, Inject()]) -> None:
        self.repository = repository


def make_app(name: str) -> App:
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": name}}))
    app.provide(Repository)
    app.provide(Service)
    return app


def test_overrides_do_not_mutate_the_original_application() -> None:
    async def scenario() -> None:
        original = make_app("original")
        replacement = Repository("override")
        override_app = original.with_overrides({Repository: replacement})

        assert original.state is LifecycleState.NEW
        assert override_app.state is LifecycleState.NEW

        async with override_app.lifespan():
            assert (await override_app.resolve(Service)).repository is replacement

        async with original.lifespan():
            service = await original.resolve(Service)
            assert service.repository is not replacement
            assert service.repository.name == "default"

        assert service.repository.closed is True

    asyncio.run(scenario())


def test_override_requires_a_registered_contract() -> None:
    app = make_app("original")

    with pytest.raises(MissingProviderError):
        app.with_overrides({"unregistered": object()})


def test_two_applications_run_concurrently_without_cross_talk() -> None:
    async def scenario() -> None:
        left = make_app("left")
        right = make_app("right")

        async with left.lifespan(), right.lifespan():
            left_service, right_service = await asyncio.gather(
                left.resolve(Service), right.resolve(Service)
            )

            assert left.settings.app.name == "left"
            assert right.settings.app.name == "right"
            assert left_service is not right_service
            assert left_service.repository is not right_service.repository

        assert left_service.repository.closed is True
        assert right_service.repository.closed is True

    asyncio.run(scenario())


def test_stopping_one_application_leaves_the_other_ready() -> None:
    async def scenario() -> None:
        left = make_app("left")
        right = make_app("right")
        await asyncio.gather(left.start(), right.start())

        await left.stop()

        assert left.state is LifecycleState.STOPPED
        assert right.state is LifecycleState.READY
        assert await right.resolve(Service) is not None

        await right.stop()

    asyncio.run(scenario())
