"""Walkthrough — migrations as a deployment step, and how to read where one landed.

Run it with:

    python -m learn_production.deploy03_migrations
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from xyberos.database import SqliteSettings, apply_migrations

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: The migrations this application ships, next to the tables they create. A deployment runs the same
#: command against this directory: `xyberos migrate --migrations ... --url ...`.
MIGRATIONS = Path(__file__).with_name("migrations")


async def apply_to(path: Path) -> None:
    """Apply every revision to the database file at ``path``, the way `xyberos migrate` does.

    Alembic's own engine is synchronous, so the URL is the *synchronous* one — which is what
    `SqliteSettings.sync_url` is for. The application keeps using the async URL for the same file.
    """
    await apply_migrations(MIGRATIONS, url=SqliteSettings(path=path).sync_url)


async def main() -> None:
    """Migrate a database, then ask the database itself where it landed."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "orders.db"
        await apply_to(path)

        engine = create_async_engine(SqliteSettings(path=path).url)
        try:
            async with engine.connect() as connection:
                version = await connection.execute(text("SELECT version_num FROM alembic_version"))
                tables = await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
                )
                print("schema version:", version.scalar_one())
                print("tables:", ", ".join(row[0] for row in tables))
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
