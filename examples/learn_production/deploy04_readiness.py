"""Walkthrough — readiness, and the choice between failing fast and reporting the truth.

Run it with:

    python -m learn_production.deploy04_readiness
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import cast

from sqlalchemy import text

from learn_production.deploy01_app import DATABASE_KEY, create_app
from learn_production.deploy03_migrations import apply_to
from xyberos import App
from xyberos.database import DatabaseProvider
from xyberos.errors import XyberosError
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


async def seed(app: App, total: float) -> None:
    """Insert the one row the walkthrough reads, through the application's own provider."""
    async with app.lifespan():
        # `resolve` returns `T` for a class and `object` for its contract overload; mypy does not
        # match the first against a Protocol class, so the runtime type is spelled out here.
        database = cast(DatabaseProvider, await app.resolve(DatabaseProvider))
        async with database.transaction() as connection:
            await connection.execute(
                text("INSERT INTO orders (id, total) VALUES (1, :total)"), {"total": total}
            )


async def scenario() -> None:
    """Ask the same application about an unreachable database, then about a real one."""
    with tempfile.TemporaryDirectory() as directory:
        # A directory is a path no SQLite file can be, which is the cheapest unreachable database.
        unreachable = str(Path(directory) / "orders.db")
        Path(unreachable).mkdir()

        patient = create_app({DATABASE_KEY: unreachable}, eager=False)
        with create_test_client(HttpAdapter(patient)) as client:
            refused = client.get("/health")
        print("eager=False ->", refused.status_code, refused.json())

        try:
            eager = create_app({DATABASE_KEY: unreachable})
            async with eager.lifespan():
                pass
        except XyberosError as error:
            cause = type(error.__cause__).__name__ if error.__cause__ else "none"
            print("eager=True  ->", type(error).__name__, "caused by", cause)
            print("and the application is left in state:", eager.state.value)

        path = Path(directory) / "migrated.db"
        await apply_to(path)
        await seed(create_app({DATABASE_KEY: str(path)}), 42.5)

        healthy = create_app({DATABASE_KEY: str(path)})
        with create_test_client(HttpAdapter(healthy)) as client:
            print("readiness ->", client.get("/health").json())
            print("GET /orders/1 ->", client.get("/orders/1").json())
            missing = client.get("/orders/7")
            print("GET /orders/7 ->", missing.status_code, missing.json())


def main() -> None:
    """Run the scenario."""
    asyncio.run(scenario())


if __name__ == "__main__":
    main()
