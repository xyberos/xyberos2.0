"""Lesson 12, exercise — a readiness check that notices a schema behind the code.

The answer to the lesson's exercise. `/health` proves the process can reach its database; it says
nothing about whether the tables the code reads are there. This one compares the columns the service
needs with the columns the database has, and answers `503` until they agree.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from sqlalchemy import Connection, text
from starlette.responses import JSONResponse, Response
from user_management.app import build_asgi_app, create_app
from user_management.identity import PrincipalVerifier
from user_management.migrate import migrate

from xyberos import App, Inject
from xyberos.database import DatabaseProvider, SqliteSettings
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")

#: What the code reads. Kept next to the check rather than derived from `tables.py`, so a column
#: that was added to the model and never migrated is a failure rather than a silent match.
EXPECTED_COLUMNS = ("id", "email", "display_name", "enabled", "external_subject")


def columns_of(connection: Connection) -> list[str]:
    """Read the users table's column names through a synchronous connection."""
    described = connection.execute(text("PRAGMA table_info(users)")).all()
    return [str(row[1]) for row in described]


class SchemaReader:
    """Answers what the database's schema is missing, without writing anything."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def missing_columns(self) -> list[str]:
        """Return the columns the code reads that the database does not have."""
        async with self._database.transaction() as connection:
            described = await connection.run_sync(columns_of)
        return sorted(set(EXPECTED_COLUMNS) - set(described))


def create_readiness_app(*, settings: SqliteSettings) -> App:
    """The lesson's application, with the exercise's readiness route added to it."""
    app = create_app(settings=settings, secret=SECRET)
    app.provide(SchemaReader)

    @app.get("/ready")
    async def ready(schema: Annotated[SchemaReader, Inject()]) -> Response:
        missing = await schema.missing_columns()
        if missing:
            return JSONResponse({"status": "not ready", "missing": missing}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app


def main() -> None:
    """Run readiness against a database the code has outgrown, then against a current one."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")

        before = build_asgi_app(create_readiness_app(settings=settings))
        with create_test_client(before) as client:
            print(
                "liveness before migrating:",
                client.get("/health").status_code,
                "(the database answers)",
            )
            not_ready = client.get("/ready")
            print("readiness before migrating:", not_ready.status_code, not_ready.json())

        migrate(settings)
        after = build_asgi_app(create_readiness_app(settings=settings))
        with create_test_client(after) as client:
            print(
                "readiness after migrating:",
                client.get("/ready").status_code,
                client.get("/ready").json(),
            )
            print(
                "and the routes still work:",
                client.get("/users", headers=ADMIN_HEADERS).status_code,
            )


if __name__ == "__main__":
    main()
