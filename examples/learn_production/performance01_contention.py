"""Walkthrough — write contention under SQLite, and the budget that keeps it bounded.

Run it with:

    python -m learn_production.performance01_contention

The numbers this prints are *counts*. A transcript that recorded durations would be a transcript
about the machine it ran on, and the point of the walkthrough is the shape of the failure, not how
fast any particular disk is.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from sqlalchemy import text

from learn_production.deploy03_migrations import apply_to
from xyberos.database import DatabaseProvider, SqliteSettings, open_database
from xyberos.errors import TransientDatabaseError

#: How many writers contend for the same row at once.
WRITERS = 20

#: The smallest busy timeout that turns contention into a refusal instead of a wait: it is shorter
#: than the lock is held on purpose, so no attempt can outlast the block.
DEADLINE_MS = 50

INCREMENT = text("UPDATE orders SET total = total + 1 WHERE id = 1")


def impatient(path: Path, attempts: int) -> SqliteSettings:
    """Return settings whose lock budget is too small to wait the held lock out."""
    return SqliteSettings(path=path, busy_timeout_ms=DEADLINE_MS, retry_attempts=attempts)


async def increment(database: DatabaseProvider) -> None:
    """Add one to the same row every other writer is adding one to."""

    async def operation(connection: object) -> None:
        await connection.execute(INCREMENT)  # type: ignore[attr-defined]

    await database.retrying(operation)


async def scenario() -> None:
    """Run one contended write, then the same write against a lock that is deliberately held."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "orders.db"
        await apply_to(path)

        database = await open_database(SqliteSettings(path=path))
        try:
            async with database.transaction() as connection:
                await connection.execute(text("INSERT INTO orders (id, total) VALUES (1, 0)"), {})

            # 20 writers, one row, every write serialised by SQLite. Each writer's budget is the
            # default five attempts, which is the setting that turns "database is locked" from a
            # request failure into a few milliseconds of waiting.
            outcomes = await asyncio.gather(
                *(increment(database) for _ in range(WRITERS)), return_exceptions=True
            )
            refused = [item for item in outcomes if isinstance(item, BaseException)]
            print(f"writers that committed: {len(outcomes) - len(refused)} of {len(outcomes)}")
            print("refusals:", [type(item).__name__ for item in refused] or "none")
            async with database.transaction() as connection:
                total = await connection.scalar(text("SELECT total FROM orders WHERE id = 1"))
            print("the row every writer touched:", total)
        finally:
            await database.aclose()

        # Now hold a write transaction open and refuse to release it, which makes contention
        # certain instead of probable: SQLite allows one writer, and this one is not finishing.
        holder = await open_database(SqliteSettings(path=path))
        impatient_one = await open_database(impatient(path, 1))
        try:
            async with holder.transaction() as connection:
                await connection.execute(text("UPDATE orders SET total = total + 100 WHERE id = 1"))
                try:
                    await increment(impatient_one)
                except TransientDatabaseError as error:
                    print("with the lock held:", type(error).__name__, "-", error)

                # A budget of one is the shortest possible answer; a longer budget is a longer wait
                # and the same refusal, which is why the retry count is a setting rather than a
                # hard-coded instinct.
                patient = await open_database(impatient(path, 3))
                try:
                    try:
                        await increment(patient)
                    except TransientDatabaseError as error:
                        print("after three attempts:", type(error).__name__, "-", error)
                finally:
                    await patient.aclose()
        finally:
            await impatient_one.aclose()
            await holder.aclose()


def main() -> None:
    """Run the scenario."""
    asyncio.run(scenario())


if __name__ == "__main__":
    main()
