"""The sqlite_crud example works end to end against a real temporary database."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlite_crud.app import app_factory, build_asgi_app, create_app
from sqlite_crud.migrate import main as migrate_main

from xyberos import LifecycleState, TransientDatabaseError
from xyberos.database import SqliteSettings, open_database, run_migrations
from xyberos.http.testing import create_test_client

MIGRATIONS = Path(__file__).resolve().parents[2] / "examples" / "sqlite_crud" / "migrations"


def migrate(settings: SqliteSettings, revision: str = "head") -> None:
    run_migrations(MIGRATIONS, url=settings.sync_url, revision=revision)


def item_columns(settings: SqliteSettings) -> set[str]:
    engine = create_engine(settings.sync_url)
    try:
        with engine.connect() as connection:
            return {row[1] for row in connection.execute(text("PRAGMA table_info(items)"))}
    finally:
        engine.dispose()


def test_migration_from_an_empty_database_creates_the_schema(tmp_path: Path) -> None:
    settings = SqliteSettings(path=tmp_path / "app.db")

    migrate(settings)

    assert item_columns(settings) == {"id", "name", "completed"}


def test_batch_migration_preserves_existing_rows(tmp_path: Path) -> None:
    settings = SqliteSettings(path=tmp_path / "app.db")
    migrate(settings, "0001_create_items")

    engine = create_engine(settings.sync_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO items (name) VALUES ('before upgrade')"))
    finally:
        engine.dispose()

    migrate(settings)

    engine = create_engine(settings.sync_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT name, completed FROM items")).all()
    finally:
        engine.dispose()

    assert rows == [("before upgrade", 0)]
    assert item_columns(settings) == {"id", "name", "completed"}


def test_crud_flow_end_to_end(tmp_path: Path) -> None:
    settings = SqliteSettings(path=tmp_path / "app.db")
    migrate(settings)
    app = create_app(settings=settings)

    with create_test_client(build_asgi_app(app)) as client:
        assert client.get("/health").json() == {"status": "ready"}
        assert client.get("/items").json() == []

        created = client.post("/items", json={"name": "write docs"})
        assert created.status_code == 200
        item = created.json()
        assert item["name"] == "write docs"
        assert item["completed"] is False

        assert client.get(f"/items/{item['id']}").json() == item
        assert client.get("/items").json() == [item]

        renamed = client.patch(f"/items/{item['id']}", json={"name": "write better docs"})
        assert renamed.json()["name"] == "write better docs"

        completed = client.patch(f"/items/{item['id']}", json={"completed": True})
        assert completed.json()["completed"] is True

        assert client.delete(f"/items/{item['id']}").status_code == 204
        assert client.get("/items").json() == []

    assert app.state is LifecycleState.STOPPED


def test_migrate_command_creates_the_database_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "var").exists()

    assert migrate_main(["migrate.py"]) == 0

    assert (tmp_path / "var" / "app.db").exists()


def test_app_factory_serves_the_default_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert migrate_main(["migrate.py"]) == 0

    with create_test_client(app_factory()) as client:
        assert client.get("/health").json() == {"status": "ready"}
        assert client.get("/items").json() == []


def test_validation_failures_and_missing_data(tmp_path: Path) -> None:
    settings = SqliteSettings(path=tmp_path / "app.db")
    migrate(settings)
    app = create_app(settings=settings)

    with create_test_client(build_asgi_app(app)) as client:
        blank = client.post("/items", json={"name": "   "})
        assert blank.status_code == 422
        assert blank.json()["error"]["type"] == "ItemValidationError"

        assert client.post("/items", content=b"not json").status_code == 422
        assert client.post("/items", json=["not", "an", "object"]).status_code == 422

        missing = client.get("/items/999")
        assert missing.status_code == 404
        assert missing.json()["error"]["type"] == "ItemNotFoundError"

        assert client.patch("/items/1", json={}).status_code == 422
        assert client.delete("/items/999").status_code == 404


def test_writes_inside_one_transaction_are_all_or_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = SqliteSettings(path=tmp_path / "app.db")
        migrate(settings)
        database = await open_database(settings)
        try:
            async with database.transaction() as connection:
                await connection.execute(text("INSERT INTO items (name) VALUES ('kept')"))

            with pytest.raises(RuntimeError):
                async with database.transaction() as connection:
                    await connection.execute(text("INSERT INTO items (name) VALUES ('lost')"))
                    raise RuntimeError("abort the transaction")

            async with database.transaction() as connection:
                names = (await connection.execute(text("SELECT name FROM items"))).scalars().all()

            assert names == ["kept"]
        finally:
            await database.aclose()

    asyncio.run(scenario())


def test_concurrent_writers_on_the_example_schema_are_bounded(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = SqliteSettings(path=tmp_path / "app.db", busy_timeout_ms=25)
        migrate(settings)
        first = await open_database(settings)
        second = await open_database(SqliteSettings(path=settings.path, busy_timeout_ms=25))
        try:
            async with first.transaction() as connection:
                await connection.execute(text("INSERT INTO items (name) VALUES ('first')"))

                async def insert_second(active: object) -> None:
                    await active.execute(  # type: ignore[attr-defined]
                        text("INSERT INTO items (name) VALUES ('second')")
                    )

                with pytest.raises(TransientDatabaseError):
                    await asyncio.wait_for(
                        second.retrying(insert_second, attempts=2, base_delay=0.01),  # type: ignore[arg-type]
                        timeout=10,
                    )
        finally:
            await first.aclose()
            await second.aclose()

    asyncio.run(scenario())
