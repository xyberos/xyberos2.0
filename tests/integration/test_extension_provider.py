"""The database-provider walkthroughs work through the public API.

The pages in ``site/extend`` claim that a provider written outside the framework is a provider:
these tests take the example module the page includes and put it in the place the claim is about —
the conformance suite, and an application's own registry.
"""

import asyncio
from pathlib import Path

import pytest
from learn_extend.provider02_registration import Inventory
from learn_extend.sql_provider import CommitsOnFailure, open_provider

from xyberos import App
from xyberos.database import DatabaseProvider
from xyberos.database.testing import assert_provider_contract


def test_the_walkthrough_provider_passes_the_conformance_suite(tmp_path: Path) -> None:
    """The six checks the page quotes are the six checks the suite runs."""

    async def scenario() -> None:
        provider = await open_provider(tmp_path / "contract.db")
        try:
            checked = await assert_provider_contract(provider, table="walkthrough_contract")
        finally:
            await provider.aclose()
        assert len(checked) == 6
        assert checked[1].startswith("transaction() commits")

    asyncio.run(scenario())


def test_the_suite_refuses_a_provider_that_commits_rolled_back_work(tmp_path: Path) -> None:
    """The refusal the page shows is a real one, not a transcript of good intentions."""

    async def scenario() -> None:
        inner = await open_provider(tmp_path / "broken.db")
        try:
            broken = CommitsOnFailure(inner)
            with pytest.raises(AssertionError, match="did not roll its work back"):
                await assert_provider_contract(broken, table="broken_contract")  # type: ignore[arg-type]
        finally:
            await inner.aclose()

    asyncio.run(scenario())


def test_a_provider_registered_under_the_protocol_serves_a_service(tmp_path: Path) -> None:
    """A service that depends on the protocol works with a provider it was never written for."""

    async def scenario() -> None:
        app = App()
        app.provide(DatabaseProvider, lambda: open_provider(tmp_path / "app.db"), eager=True)
        app.provide(Inventory)

        async with app.lifespan():
            inventory = await app.resolve(Inventory)
            await inventory.prepare()
            for name in ("widget", "sprocket"):
                await inventory.add(name)
            assert await inventory.count() == 2
            assert await inventory.ready() is True
            assert [(info.contract, info.eager) for info in app.diagnostics().providers] == [
                ("DatabaseProvider", True),
                ("Inventory", False),
            ]

        # The application closed the provider it owns, so readiness is no longer a matter of
        # opinion.
        assert await inventory.ready() is False

    asyncio.run(scenario())
