"""Lesson 7 — the schema as a version, applied by a command.

Run it with:

    python -m learn_traditional.traditional07_migrations
"""

from __future__ import annotations

import contextlib
import io
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text
from user_management.app import create_app
from user_management.identity import PrincipalVerifier
from user_management.migrate import MIGRATIONS, migrate

from xyberos.cli.main import main as xyberos_main
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
#: The administrator's assertion, presented once and carried by every request.
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")


def revision(settings: SqliteSettings) -> str:
    """Read the revision the database is currently at."""
    engine = create_engine(settings.sync_url)
    try:
        with engine.connect() as connection:
            recorded = connection.execute(text("SELECT version_num FROM alembic_version"))
            return str(recorded.scalar_one())
    finally:
        engine.dispose()


def columns(settings: SqliteSettings) -> list[str]:
    """Read the column names of the users table, as the database itself reports them."""
    engine = create_engine(settings.sync_url)
    try:
        with engine.connect() as connection:
            described = connection.execute(text("PRAGMA table_info(users)"))
            return [str(row[1]) for row in described]
    finally:
        engine.dispose()


def deploy_command(settings: SqliteSettings) -> str:
    """Run the documented deploy command, and report it without the temporary paths."""
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = xyberos_main(
            ["migrate", "--url", settings.sync_url, "--migrations", str(MIGRATIONS)]
        )
    report = captured.getvalue().strip()
    readable = report.replace(str(MIGRATIONS), "<migrations>").replace(
        settings.sync_url, "<database>"
    )
    return f"{readable}, exit {code}"


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")

        migrate(settings)
        print("migrated to", revision(settings))
        print("users columns:", columns(settings))

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            created = client.post(
                "/users", json={"email": "ada@example.com", "display_name": "Ada Lovelace"}
            )
            print("created:", created.json())

            print("the deploy step:", deploy_command(settings))

            migrate(settings)
            print("migrating again leaves the revision at", revision(settings))
            print("the user that existed before is still there:", client.get("/users/1").json())


if __name__ == "__main__":
    main()
