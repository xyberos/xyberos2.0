"""Lesson 3 — storing data in SQLite.

Run it with:

    python -m learn_traditional.traditional03_database
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from sqlalchemy import Column, Integer, MetaData, String, Table, func, insert, select

from xyberos import App, Inject
from xyberos.database import temporary_database
from xyberos.database.contracts import DatabaseProvider

metadata = MetaData()

items = Table(
    "items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False),
)


class ItemStore:
    """A service that owns its SQL, and nothing about HTTP."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def create_schema(self) -> None:
        """Create the table, which a real application would do with a migration."""
        async with self._database.transaction() as connection:
            await connection.run_sync(metadata.create_all)

    async def add(self, name: str) -> None:
        """Insert one item."""
        async with self._database.transaction() as connection:
            await connection.execute(insert(items).values(name=name))

    async def add_then_fail(self, name: str) -> None:
        """Insert one item and then raise, so the transaction rolls back."""
        async with self._database.transaction() as connection:
            await connection.execute(insert(items).values(name=name))
            raise RuntimeError("something went wrong after the insert")

    async def all(self) -> list[dict[str, Any]]:
        """Return every item."""
        async with self._database.transaction() as connection:
            rows = (await connection.execute(select(items))).mappings().all()
        return [dict(row) for row in rows]

    async def count(self) -> int:
        """Return how many items are stored."""
        async with self._database.transaction() as connection:
            return int(
                (await connection.execute(select(func.count()).select_from(items))).scalar_one()
            )


async def main() -> None:
    async with temporary_database() as database:
        app = App()
        app.provide(DatabaseProvider, instance=database)
        app.provide(ItemStore)

        async with app.lifespan():
            store = await app.resolve(ItemStore)
            await store.create_schema()
            await store.add("notebook")
            print("rows:", await store.all())

            try:
                await store.add_then_fail("lost")
            except RuntimeError:
                pass
            print("rows after the rollback:", await store.count())


if __name__ == "__main__":
    asyncio.run(main())
