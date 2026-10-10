"""The SQLite provider owns configuration, PRAGMAs, transactions, and bounded retries."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from xyberos import DatabaseConfigurationError, DatabaseConnectionError, TransientDatabaseError
from xyberos.database import SqliteDatabase, SqliteSettings, open_database, temporary_database


async def create_table(database: SqliteDatabase, name: str = "t") -> None:
    async with database.transaction() as connection:
        await connection.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, name TEXT)"))


def test_settings_are_normalized_and_expose_urls(tmp_path: Path) -> None:
    settings = SqliteSettings(path=tmp_path / "app.db", journal_mode="wal", synchronous="normal")

    assert settings.journal_mode == "WAL"
    assert settings.synchronous == "NORMAL"
    assert settings.url.startswith("sqlite+aiosqlite:///")
    assert settings.sync_url.startswith("sqlite:///")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"journal_mode": "bogus"},
        {"synchronous": "bogus"},
        {"busy_timeout_ms": -1},
        {"retry_attempts": 0},
        {"retry_base_delay": -0.1},
    ],
)
def test_invalid_settings_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(DatabaseConfigurationError):
        SqliteSettings(**kwargs)


def test_in_memory_databases_cannot_use_wal() -> None:
    with pytest.raises(DatabaseConfigurationError):
        SqliteSettings(path=":memory:", journal_mode="WAL")


def test_the_engine_is_unavailable_before_start() -> None:
    database = SqliteDatabase()

    with pytest.raises(DatabaseConnectionError):
        _ = database.engine


def test_start_installs_the_documented_pragmas(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with temporary_database(directory=tmp_path, busy_timeout_ms=2500) as database:
            async with database.engine.connect() as connection:
                pragmas = {
                    name: (await connection.execute(text(f"PRAGMA {name}"))).scalar()
                    for name in ("foreign_keys", "journal_mode", "synchronous", "busy_timeout")
                }

            assert pragmas["foreign_keys"] == 1
            assert pragmas["journal_mode"] == "wal"
            assert pragmas["synchronous"] == 1
            assert pragmas["busy_timeout"] == 2500

    asyncio.run(scenario())


def test_temporary_database_is_a_real_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with temporary_database(directory=tmp_path) as database:
            assert Path(str(database.settings.path)).exists()

    asyncio.run(scenario())


def test_start_creates_a_missing_parent_directory(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = SqliteSettings(path=tmp_path / "nested" / "deeper" / "app.db")
        database = await open_database(settings)
        try:
            assert settings.file_path is not None
            assert settings.file_path.parent.is_dir()
            await database.health()
        finally:
            await database.aclose()

    asyncio.run(scenario())


def test_transactions_commit_and_roll_back(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with temporary_database(directory=tmp_path) as database:
            await create_table(database)

            async with database.transaction() as connection:
                await connection.execute(text("INSERT INTO t (id, name) VALUES (1, 'kept')"))

            with pytest.raises(RuntimeError):
                async with database.transaction() as connection:
                    await connection.execute(text("INSERT INTO t (id, name) VALUES (2, 'lost')"))
                    raise RuntimeError("rollback")

            async with database.transaction() as connection:
                rows = (
                    (await connection.execute(text("SELECT id FROM t ORDER BY id"))).scalars().all()
                )

            assert rows == [1]

    asyncio.run(scenario())


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with temporary_database(directory=tmp_path) as database:
            async with database.transaction() as connection:
                await connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
                await connection.execute(
                    text(
                        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL "
                        "REFERENCES parent(id))"
                    )
                )

            with pytest.raises(IntegrityError):
                async with database.transaction() as connection:
                    await connection.execute(
                        text("INSERT INTO child (id, parent_id) VALUES (1, 99)")
                    )

    asyncio.run(scenario())


def test_health_and_close(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = await open_database(SqliteSettings(path=tmp_path / "app.db"))

        await database.health()
        await database.aclose()

        with pytest.raises(DatabaseConnectionError):
            await database.health()

    asyncio.run(scenario())


def test_retrying_recovers_once_the_writer_releases_the_lock(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with temporary_database(directory=tmp_path, busy_timeout_ms=50) as database:
            await create_table(database)
            blocker = SqliteDatabase(SqliteSettings(path=database.settings.path, busy_timeout_ms=0))
            await blocker.start()
            try:
                async with blocker.engine.connect() as connection:
                    transaction = await connection.begin()
                    await connection.execute(text("INSERT INTO t (id, name) VALUES (1, 'blocker')"))

                    async def insert(active: AsyncConnection) -> int:
                        await active.execute(text("INSERT INTO t (id, name) VALUES (2, 'writer')"))
                        return 2

                    attempt = asyncio.create_task(
                        database.retrying(insert, attempts=40, base_delay=0.05)
                    )
                    await asyncio.sleep(0.3)
                    await transaction.rollback()

                    assert await asyncio.wait_for(attempt, timeout=10) == 2
            finally:
                await blocker.aclose()

    asyncio.run(scenario())


def test_retrying_fails_within_its_budget_and_never_hangs(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with temporary_database(directory=tmp_path, busy_timeout_ms=25) as database:
            await create_table(database)
            blocker = SqliteDatabase(
                SqliteSettings(path=database.settings.path, busy_timeout_ms=25)
            )
            await blocker.start()
            try:
                async with blocker.engine.connect() as connection:
                    transaction = await connection.begin()
                    await connection.execute(text("INSERT INTO t (id, name) VALUES (1, 'blocker')"))

                    async def insert(active: AsyncConnection) -> int:
                        await active.execute(text("INSERT INTO t (id, name) VALUES (2, 'writer')"))
                        return 2

                    with pytest.raises(TransientDatabaseError):
                        await asyncio.wait_for(
                            database.retrying(insert, attempts=2, base_delay=0.01), timeout=10
                        )

                    await transaction.rollback()
            finally:
                await blocker.aclose()

    asyncio.run(scenario())
