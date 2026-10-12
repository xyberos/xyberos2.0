"""Walkthrough — giving an application a database provider of your own.

Run it with:

    python -m learn_extend.provider02_registration
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Annotated

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from learn_extend.sql_provider import open_provider
from xyberos import App, Inject
from xyberos.database import DatabaseProvider
from xyberos.errors import DatabaseConnectionError

#: The table this walkthrough uses. The provider knows nothing about it: that is the service's
#: business.
SCHEMA = "CREATE TABLE IF NOT EXISTS items (name TEXT NOT NULL)"


class Inventory:
    """A service that depends on the contract, not on the engine behind it."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def prepare(self) -> None:
        """Create the table this service owns, in a transaction of its own."""
        async with self._database.transaction() as connection:
            await connection.execute(text(SCHEMA))

    async def add(self, name: str) -> None:
        """Write one row, in a transaction this service owns."""
        async with self._database.transaction() as connection:
            await connection.execute(
                text("INSERT INTO items (name) VALUES (:name)"), {"name": name}
            )

    async def count(self) -> int:
        """Count the rows, retrying if another writer holds the lock."""

        async def read(connection: AsyncConnection) -> int:
            result = await connection.execute(text("SELECT COUNT(*) FROM items"))
            return int(result.scalar_one())

        return await self._database.retrying(read)

    async def ready(self) -> bool:
        """Answer the question a readiness endpoint asks, rather than assuming it."""
        try:
            await self._database.health()
        except DatabaseConnectionError:
            return False
        return True


async def main() -> None:
    """Register the provider eagerly, use it through a service, and let shutdown close it."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "inventory.db"
        app = App()
        app.provide(DatabaseProvider, lambda: open_provider(path), eager=True)
        app.provide(Inventory)

        async with app.lifespan():
            print(app.diagnostics().render().strip())
            inventory = await app.resolve(Inventory)
            await inventory.prepare()
            for name in ("widget", "sprocket", "cog"):
                await inventory.add(name)
            print("a service counted its own rows:", await inventory.count())
            print("the service asked the provider whether it was ready:", await inventory.ready())

        print("after shutdown, the same question answers:", await inventory.ready())


if __name__ == "__main__":
    asyncio.run(main())
