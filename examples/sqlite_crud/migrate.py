"""Apply the example's Alembic migrations.

Usage: python examples/sqlite_crud/migrate.py [path/to/app.db]
"""

from __future__ import annotations

import sys
from pathlib import Path

from xyberos.database import SqliteSettings, run_migrations

MIGRATIONS = Path(__file__).parent / "migrations"


def main(argv: list[str]) -> int:
    database_path = argv[1] if len(argv) > 1 else "var/app.db"
    settings = SqliteSettings(path=database_path)
    file_path = settings.file_path
    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    run_migrations(MIGRATIONS, url=settings.sync_url)
    print(f"migrated {settings.sync_url} to head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
