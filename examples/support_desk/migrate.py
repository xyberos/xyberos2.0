"""Apply the desk's migrations.

This is the deploy step: a command someone runs against a database, never something the application
does to itself at startup.

Usage: python examples/support_desk/migrate.py [path/to/support.db]
"""

from __future__ import annotations

import sys
from pathlib import Path

from xyberos.database import SqliteSettings, run_migrations

MIGRATIONS = Path(__file__).parent / "migrations"


def migrate(settings: SqliteSettings, *, revision: str = "head") -> None:
    """Apply every revision up to ``revision`` to this database."""
    file_path = settings.file_path
    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    run_migrations(MIGRATIONS, url=settings.sync_url, revision=revision)


def main(argv: list[str]) -> int:
    """Apply the migrations, for a deployment step or a local reset."""
    settings = SqliteSettings(path=argv[1] if len(argv) > 1 else "var/support.db")
    migrate(settings)
    print(f"migrated {settings.sync_url} to head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
