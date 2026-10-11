"""Chapter 8 — writing your first test, as a test.

This file *is* the chapter: copy it into your own project as `tests/test_app.py` and run `pytest`.
There is no Xyberos test runner and no plugin to install. A test is an ordinary pytest test, and
what the framework ships is the doubles that make it fast — plus one rule worth learning early: **a
test double has to satisfy the contract**, which is why the application is written against a
`Protocol` rather than against the class that happens to implement it today.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Protocol

from xyberos import App, Inject
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


class ItemReader(Protocol):
    """The contract: what a caller needs, not what an implementation is."""

    def all(self) -> list[str]:
        """Return every stored item."""
        ...


class ItemStore:
    """The real implementation: no HTTP types, so it is testable on its own."""

    def __init__(self) -> None:
        self._items: list[str] = []

    def add(self, name: str) -> None:
        """Store one item."""
        self._items.append(name)

    def all(self) -> list[str]:
        """Return every stored item."""
        return list(self._items)


class FakeItemStore:
    """A test double that satisfies the same contract, and answers instantly."""

    def all(self) -> list[str]:
        """Return a fixed list."""
        return ["from the fake"]


def create_app() -> App:
    """Build the application the tests exercise."""
    app = App()
    app.provide(ItemReader, instance=ItemStore())

    @app.get("/items")
    async def list_items(items: Annotated[ItemReader, Inject()]) -> list[str]:
        return items.all()

    return app


def test_a_service_can_be_used_without_http() -> None:
    """The cheapest test: no application, no request, no server."""

    def scenario() -> None:
        store = ItemStore()
        store.add("notebook")

        assert store.all() == ["notebook"]

    scenario()


def test_the_route_answers() -> None:
    """Use the test client as a context manager, so the application's lifespan runs."""
    with create_test_client(HttpAdapter(create_app())) as client:
        response = client.get("/items")

        assert response.status_code == 200
        assert response.json() == []


def test_a_dependency_can_be_replaced() -> None:
    """Override the *contract*.

    `with_overrides` returns an independent application, so an override cannot leak into another
    test, and the double is checked against the contract when it is first resolved.
    """
    app = create_app().with_overrides({ItemReader: FakeItemStore()})

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/items").json() == ["from the fake"]


def test_the_application_validates_and_starts() -> None:
    """Composition errors are startup errors, so a test can catch them early."""

    async def scenario() -> None:
        app = create_app()
        app.validate()

        async with app.lifespan():
            reader = await app.resolve(ItemReader)
            assert reader.all() == []

    asyncio.run(scenario())
