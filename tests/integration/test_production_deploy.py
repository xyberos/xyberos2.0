"""The deployment page's claims are exercised, not just transcribed.

``examples/learn_production/deploy01_app.py`` is the application behind `site/production/deploy.md`,
and the walkthrough modules print what it does. What this file holds is what a transcript cannot:
that the factory contracts are what the page says a deployment can rely on, that the two postures
towards a broken database differ in the way the page claims, and that Alembic really does need the
synchronous URL."""

import asyncio
from pathlib import Path

import pytest
from learn_production.deploy01_app import (
    DATABASE_KEY,
    OrderService,
    create_app,
    create_asgi,
)
from learn_production.deploy03_migrations import MIGRATIONS, apply_to
from sqlalchemy import text
from starlette.applications import Starlette

from xyberos import App
from xyberos.database import DatabaseProvider, SqliteSettings, apply_migrations
from xyberos.errors import DatabaseConnectionError, LifecycleStateError, XyberosError
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

UNREACHABLE = "sqlite+aiosqlite:///not/a/directory/orders.db"


def unreachable_database(tmp_path: Path) -> str:
    """Return a path no SQLite file can be, which is the cheapest unreachable database."""
    directory = tmp_path / "orders.db"
    directory.mkdir()
    return str(directory)


async def seed(app: App, total: float) -> None:
    """Insert the row the readiness assertions read, through the application's own provider."""
    async with app.lifespan():
        database = await app.resolve(DatabaseProvider)
        async with database.transaction() as connection:
            await connection.execute(
                text("INSERT INTO orders (id, total) VALUES (1, :total)"), {"total": total}
            )


def test_the_runtime_factory_validates_without_starting_anything() -> None:
    app = create_app()
    plan = app.validate()

    assert app.state.value == "validated"
    assert [provider.contract for provider in plan] == [DatabaseProvider, OrderService]


def test_the_asgi_factory_builds_something_a_server_can_serve() -> None:
    assert isinstance(create_asgi(), Starlette)
    assert isinstance(create_asgi(eager=False), Starlette)


def test_eager_startup_turns_an_unreachable_database_into_a_failed_start(tmp_path: Path) -> None:
    app = create_app({DATABASE_KEY: unreachable_database(tmp_path)})

    with pytest.raises(XyberosError) as raised:
        asyncio.run(app.start())

    assert app.state.value == "failed"
    assert isinstance(raised.value.__cause__, DatabaseConnectionError)


def test_the_tolerant_posture_reports_readiness_instead_of_refusing_to_start(
    tmp_path: Path,
) -> None:
    app = create_app({DATABASE_KEY: unreachable_database(tmp_path)}, eager=False)

    with create_test_client(HttpAdapter(app)) as client:
        refused = client.get("/health")

    assert refused.status_code == 503
    assert refused.json() == {
        "error": {"type": "NotReadyError", "message": "the database is not reachable"}
    }
    # The body names the application's own error and nothing about the database it could not reach.
    assert "directory" not in refused.text


def test_readiness_and_the_404_both_reflect_the_real_database(tmp_path: Path) -> None:
    path = tmp_path / "orders.db"
    asyncio.run(apply_to(path))
    asyncio.run(seed(create_app({DATABASE_KEY: str(path)}), 42.5))

    app = create_app({DATABASE_KEY: str(path)})
    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/health").json() == {"ready": True}
        assert client.get("/orders/1").json() == {"order": 1, "total": 42.5}
        missing = client.get("/orders/7")

    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"type": "OrderNotFoundError", "message": "order 7 does not exist"}
    }


def test_a_stopped_application_does_not_start_again() -> None:
    app = create_app()

    async def scenario() -> None:
        async with app.lifespan():
            pass
        with pytest.raises(LifecycleStateError):
            await app.start()

    asyncio.run(scenario())


def test_migrations_need_the_synchronous_url(tmp_path: Path) -> None:
    path = tmp_path / "orders.db"
    settings = SqliteSettings(path=path)

    with pytest.raises(Exception, match="greenlet_spawn"):
        asyncio.run(apply_migrations(MIGRATIONS, url=settings.url))

    asyncio.run(apply_migrations(MIGRATIONS, url=settings.sync_url))
    assert path.exists()
