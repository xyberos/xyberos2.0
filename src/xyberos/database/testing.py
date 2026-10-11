"""Test utilities for the database extra."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import Column, Integer, MetaData, String, Table, delete, func, insert, select

try:
    from xyberos.database.contracts import DatabaseProvider
    from xyberos.database.sqlite import SqliteDatabase, SqliteSettings, open_database
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("database", error) from error

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = ["assert_provider_contract", "temporary_database"]


@asynccontextmanager
async def temporary_database(
    *,
    directory: Path | None = None,
    journal_mode: str = "WAL",
    synchronous: str = "NORMAL",
    busy_timeout_ms: int = 5000,
) -> AsyncIterator[SqliteDatabase]:
    """Yield a started database backed by a real temporary file, then close and remove it.

    A real file is used rather than an in-memory database so that WAL mode, file locking, and
    restart behavior are exercised exactly as they are in production.
    """
    if directory is not None:
        database = await open_database(
            SqliteSettings(
                path=directory / "test.db",
                journal_mode=journal_mode,
                synchronous=synchronous,
                busy_timeout_ms=busy_timeout_ms,
            )
        )
        try:
            yield database
        finally:
            await database.aclose()
        return

    with tempfile.TemporaryDirectory(prefix="xyberos-test-") as temporary:
        database = await open_database(
            SqliteSettings(
                path=Path(temporary) / "test.db",
                journal_mode=journal_mode,
                synchronous=synchronous,
                busy_timeout_ms=busy_timeout_ms,
            )
        )
        try:
            yield database
        finally:
            await database.aclose()


class _ExpectedRollback(Exception):
    """The failure a rollback check raises on purpose; never escapes this module."""


CONCURRENT_WRITERS = 4


async def assert_provider_contract(
    provider: DatabaseProvider,
    *,
    table: str = "xyberos_conformance",
) -> tuple[str, ...]:
    """Check that ``provider`` behaves the way :class:`DatabaseProvider` says, and report what ran.

    This is the suite a provider author outside this project runs against their own
    implementation — the same claims are checked here as against the shipped SQLite provider, so "we
    support a different database" means evidence rather than intent. It raises ``AssertionError``
    naming the check that failed, so it is usable from pytest, an ordinary script, or another test
    runner.

    The checks are about the contract, not about performance, isolation levels beyond the documented
    ones, or operational maturity. A provider that passes can still be wrong for a workload.
    """
    metadata = MetaData()
    items = Table(
        table,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(64), nullable=False),
    )
    checked: list[str] = []

    async def count() -> int:
        async with provider.transaction() as connection:
            return int(
                (await connection.execute(select(func.count()).select_from(items))).scalar_one()
            )

    async def insert_one(connection: AsyncConnection, name: str) -> None:
        await connection.execute(insert(items).values(name=name))

    async def prepare() -> None:
        async with provider.transaction() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(delete(items))

    try:
        await provider.health()
        checked.append("health() succeeds for a working provider")

        await prepare()

        async with provider.transaction() as connection:
            await insert_one(connection, "committed")
        if await count() != 1:
            raise AssertionError("a transaction that returned normally did not commit its work")
        checked.append("transaction() commits when the body returns")

        try:
            async with provider.transaction() as connection:
                await insert_one(connection, "rolled-back")
                raise _ExpectedRollback
        except _ExpectedRollback:
            pass
        else:
            raise AssertionError("transaction() swallowed the error the body raised")
        if await count() != 1:
            raise AssertionError("a transaction that raised did not roll its work back")
        checked.append("transaction() rolls back and re-raises when the body raises")

        async with provider.transaction() as connection:
            await insert_one(connection, "after-failure")
        if await count() != 2:
            raise AssertionError("the provider could not be used again after a failed transaction")
        checked.append("a failed transaction leaves the provider usable")

        async def insert_and_report(connection: AsyncConnection) -> int:
            await insert_one(connection, "retried")
            return 7

        result = await provider.retrying(insert_and_report, attempts=5, base_delay=0.01)
        if result != 7:
            raise AssertionError("retrying() did not return the operation's result")
        if await count() != 3:
            raise AssertionError("retrying() did not run the operation")
        checked.append("retrying() runs the operation and returns its value")

        async def write(index: int) -> None:
            async def operation(connection: AsyncConnection) -> None:
                await insert_one(connection, f"concurrent-{index}")

            await provider.retrying(operation, attempts=10, base_delay=0.01)

        await asyncio.gather(*(write(index) for index in range(CONCURRENT_WRITERS)))
        if await count() != 3 + CONCURRENT_WRITERS:
            raise AssertionError("concurrent writers did not all commit")
        checked.append(f"retrying() lets {CONCURRENT_WRITERS} concurrent writers finish")
    finally:
        # Cleanup is best-effort: a suite that raised must report *its* failure, not one produced by
        # the teardown of a provider that is already misbehaving.
        try:
            async with provider.transaction() as connection:
                await connection.run_sync(metadata.drop_all)
        except Exception:
            pass

    return tuple(checked)
