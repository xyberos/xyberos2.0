"""Lesson 7, exercise — a revision that changes a table which already has rows.

The answer to the lesson's exercise. The revision is a file next to this module; the answer copies
the project's migration directory to a temporary one and drops the revision into it, which is what
you would do in your project by writing the file into ``migrations/versions/``.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from user_management.migrate import MIGRATIONS, migrate

from xyberos.database import SqliteSettings, run_migrations

EXERCISE_MIGRATIONS = Path(__file__).parent / "migrations_exercise"


def read(settings: SqliteSettings, statement: str) -> Any:
    """Run one statement against the database and return what it produced."""
    engine = create_engine(settings.sync_url)
    try:
        with engine.connect() as connection:
            return connection.execute(text(statement)).all()
    finally:
        engine.dispose()


def revision(settings: SqliteSettings) -> str:
    """Read the revision the database is currently at."""
    return str(read(settings, "SELECT version_num FROM alembic_version")[0][0])


def columns(settings: SqliteSettings) -> list[str]:
    """Read the column names of the users table."""
    return [str(row[1]) for row in read(settings, "PRAGMA table_info(users)")]


def the_row(settings: SqliteSettings) -> Any:
    """Read the only row in the table."""
    return dict(read(settings, "SELECT * FROM users")[0]._mapping)


def main() -> None:
    """Install the schema, add a row, then change the table underneath it."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings, revision="0001_create_users")

        print("migrated to", revision(settings))
        print("users columns:", columns(settings))

        engine = create_engine(settings.sync_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users (email, display_name, enabled) "
                        "VALUES ('ada@example.com', 'Ada Lovelace', 1)"
                    )
                )
        finally:
            engine.dispose()
        print("the row before the change:", the_row(settings))

        working = Path(directory) / "migrations"
        shutil.copytree(MIGRATIONS, working)
        shutil.copy(EXERCISE_MIGRATIONS / "0003_add_nickname.py", working / "versions")
        run_migrations(working, url=settings.sync_url)

        print("migrated to", revision(settings))
        print("users columns:", columns(settings))
        print("the same row after the change:", the_row(settings))


if __name__ == "__main__":
    main()
