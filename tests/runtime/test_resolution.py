"""Scope caching, resolution paths, and request boundaries."""

import asyncio
from typing import Annotated

import pytest

from xyberos import (
    App,
    DependencyResolutionError,
    Inject,
    LifecycleStateError,
    Scope,
    Settings,
)


class Repository:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class Service:
    def __init__(self, repository: Annotated[Repository, Inject()]) -> None:
        self.repository = repository


class RequestUnit:
    def __init__(self, service: Annotated[Service, Inject()]) -> None:
        self.service = service


class TransientUnit:
    pass


class OtherLeaf:
    pass


class GreetingConsumer:
    def __init__(self, greeting: Annotated[str, Inject(contract="greeting")]) -> None:
        self.greeting = greeting


class ManagedTransient:
    async def aclose(self) -> None: ...


def broken_repository() -> Repository:
    raise RuntimeError("repository unavailable")


def build_app() -> App:
    app = App(settings=Settings.load(environ={}))
    app.provide(Repository)
    app.provide(Service)
    app.provide(RequestUnit, scope=Scope.REQUEST)
    app.provide(TransientUnit, scope=Scope.TRANSIENT)
    app.validate()
    return app


def test_app_scope_caches_while_transient_does_not() -> None:
    async def scenario() -> None:
        app = build_app()
        await app.start()

        service = await app.resolve(Service)
        assert await app.resolve(Service) is service
        assert await app.resolve(TransientUnit) is not await app.resolve(TransientUnit)

        await app.stop()

    asyncio.run(scenario())


def test_request_scope_caches_within_a_request_and_isolates_requests() -> None:
    async def scenario() -> None:
        app = build_app()
        await app.start()

        async with app.request_context() as request:
            first = await request.resolve(RequestUnit)
            assert await request.resolve(RequestUnit) is first

        async with app.request_context() as request:
            assert await request.resolve(RequestUnit) is not first

        await app.stop()

    asyncio.run(scenario())


def test_request_scoped_services_share_app_scoped_services() -> None:
    async def scenario() -> None:
        app = build_app()
        await app.start()

        service = await app.resolve(Service)
        async with app.request_context() as request:
            unit = await request.resolve(RequestUnit)
            assert unit.service is service

        await app.stop()

    asyncio.run(scenario())


def test_request_scope_requires_an_active_request_context() -> None:
    async def scenario() -> None:
        app = build_app()
        await app.start()

        with pytest.raises(DependencyResolutionError):
            await app.resolve(RequestUnit)

        await app.stop()

    asyncio.run(scenario())


def test_closed_request_context_rejects_further_resolution() -> None:
    async def scenario() -> None:
        app = build_app()
        await app.start()

        async with app.request_context() as request:
            pass

        with pytest.raises(LifecycleStateError):
            await request.resolve(RequestUnit)

        await app.stop()

    asyncio.run(scenario())


def test_resolution_requires_a_ready_application() -> None:
    async def scenario() -> None:
        app = build_app()

        with pytest.raises(LifecycleStateError):
            await app.resolve(Service)

        await app.start()
        await app.stop()

        with pytest.raises(LifecycleStateError):
            await app.resolve(Service)

    asyncio.run(scenario())


def test_resolution_failures_preserve_the_path_and_root_cause() -> None:
    async def scenario() -> None:
        app = App(settings=Settings.load(environ={}))
        app.provide(Repository, factory=broken_repository)
        app.provide(Service)
        await app.start()

        with pytest.raises(DependencyResolutionError) as info:
            await app.resolve(Service)

        assert info.value.path == (Service, Repository)
        assert isinstance(info.value.__cause__, RuntimeError)

        await app.stop()

    asyncio.run(scenario())


def test_instance_type_mismatch_is_reported_when_resolved() -> None:
    async def scenario() -> None:
        app = App(settings=Settings.load(environ={}))
        app.provide(Repository, instance=OtherLeaf())
        await app.start()

        with pytest.raises(DependencyResolutionError):
            await app.resolve(Repository)

        await app.stop()

    asyncio.run(scenario())


def test_transient_providers_may_not_return_managed_resources() -> None:
    async def scenario() -> None:
        app = App(settings=Settings.load(environ={}))
        app.provide(ManagedTransient, scope=Scope.TRANSIENT)
        await app.start()

        with pytest.raises(DependencyResolutionError):
            await app.resolve(ManagedTransient)

        await app.stop()

    asyncio.run(scenario())


def test_explicit_contract_marks_support_opaque_keys() -> None:
    async def scenario() -> None:
        app = App(settings=Settings.load(environ={}))
        app.provide("greeting", instance="hello")
        app.provide(GreetingConsumer)
        await app.start()

        consumer = await app.resolve(GreetingConsumer)

        assert consumer.greeting == "hello"
        await app.stop()

    asyncio.run(scenario())
