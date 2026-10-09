from __future__ import annotations

import asyncio
import os

from xyberos.providers.database import SQLiteProvider

from .app import migrate_schema


async def run_migrations(database_path: str) -> tuple[int, ...]:
    provider = SQLiteProvider()
    await provider.initialize(
        {
            "path": database_path,
            "journal_mode": "WAL",
            "busy_timeout_ms": 30_000,
        }
    )
    try:
        return await migrate_schema(provider)
    finally:
        await provider.close()


def main() -> None:
    database_path = os.environ.get("XYBEROS_DATABASE_PATH", "./data/example.db")
    applied = asyncio.run(run_migrations(database_path))
    print(f"Applied schema migrations: {applied or 'none (already current)'}")


if __name__ == "__main__":
    main()
