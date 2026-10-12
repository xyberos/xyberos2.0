"""Lesson 3, exercise — a rename method, and the SQL it runs.

The answer to the lesson's exercise. The only new idea is `update`, and it is still inside one
transaction: a write that raises leaves the row as it was.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, update

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

    async def rename(self, item_id: int, name: str) -> None:
        """Rename one item."""
        async with self._database.transaction() as connection:
            await connection.execute(update(items).where(items.c.id == item_id).values(name=name))

    async def all(self) -> list[dict[str, Any]]:
        """Return every item."""
        async with self._database.transaction() as connection:
            rows = (await connection.execute(select(items))).mappings().all()
        return [dict(row) for row in rows]


async def main() -> None:
    """Store one item, rename it, and read it back."""
    async with temporary_database() as database:
        app = App()
        app.provide(DatabaseProvider, instance=database)
        app.provide(ItemStore)

        async with app.lifespan():
            store = await app.resolve(ItemStore)
            await store.create_schema()
            await store.add("notebook")
            await store.rename(1, "diary")
            print("after the rename:", await store.all())


if __name__ == "__main__":
    asyncio.run(main())
