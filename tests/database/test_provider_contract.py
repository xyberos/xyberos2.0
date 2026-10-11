"""The database provider contract, checked against the provider we ship.

`assert_provider_contract` exists so that a provider author outside this project can prove their
implementation behaves the way the contract says. That makes two things worth testing here: that
the shipped SQLite provider passes, and that the suite *fails* for a provider that breaks the
contract. A conformance suite that passes for everything would be worse than none, because it would
be evidence that means nothing.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from xyberos.database import temporary_database
from xyberos.database.testing import assert_provider_contract

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from xyberos.database.contracts import DatabaseProvider


def test_the_shipped_sqlite_provider_satisfies_the_contract() -> None:
    async def scenario() -> tuple[str, ...]:
        async with temporary_database() as database:
            return await assert_provider_contract(database)

    checked = asyncio.run(scenario())

    assert len(checked) == 6
    assert any("commits" in name for name in checked)
    assert any("rolls back" in name for name in checked)
    assert any("retrying() runs" in name for name in checked)
    assert any("concurrent writers" in name for name in checked)


def test_the_contract_is_checkable_twice_on_one_database() -> None:
    """The suite leaves nothing behind, so it can run again against the same provider."""

    async def scenario() -> None:
        async with temporary_database() as database:
            await assert_provider_contract(database)
            await assert_provider_contract(database, table="xyberos_conformance_again")

    asyncio.run(scenario())


class RollbackIgnoringProvider:
    """A provider that commits work a failed transaction should have rolled back.

    This is the mistake the contract exists to prevent: partial work committed by a transaction
    whose body raised. Nothing about it is obviously broken at the call site.
    """

    def __init__(self, inner: DatabaseProvider) -> None:
        self._inner = inner

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self._inner.transaction() as connection:
            try:
                yield connection
            except Exception:
                await connection.commit()
                raise

    def retrying(
        self, operation: object, *, attempts: int | None = None, base_delay: float | None = None
    ) -> object:
        retry = self._inner.retrying(  # type: ignore[arg-type]
            operation, attempts=attempts, base_delay=base_delay
        )
        return retry

    async def health(self) -> None:
        await self._inner.health()


@pytest.mark.filterwarnings("ignore::sqlalchemy.exc.SAWarning")
def test_the_suite_catches_a_provider_that_commits_rolled_back_work() -> None:
    async def scenario() -> None:
        async with temporary_database() as database:
            broken = RollbackIgnoringProvider(database)
            with pytest.raises(AssertionError, match="did not roll its work back"):
                await assert_provider_contract(broken)  # type: ignore[arg-type]

    asyncio.run(scenario())


class RealCommitProvider:
    """A provider whose ``retrying`` does not return the operation's result."""

    def __init__(self, inner: DatabaseProvider) -> None:
        self._inner = inner

    def transaction(self) -> object:
        return self._inner.transaction()

    async def retrying(
        self, operation: object, *, attempts: int | None = None, base_delay: float | None = None
    ) -> None:
        await self._inner.retrying(  # type: ignore[arg-type]
            operation, attempts=attempts, base_delay=base_delay
        )
        return None

    async def health(self) -> None:
        await self._inner.health()


def test_the_suite_catches_a_provider_that_drops_the_operation_result() -> None:
    async def scenario() -> None:
        async with temporary_database() as database:
            broken = RealCommitProvider(database)
            with pytest.raises(AssertionError, match="did not return the operation's result"):
                await assert_provider_contract(broken)  # type: ignore[arg-type]

    asyncio.run(scenario())
