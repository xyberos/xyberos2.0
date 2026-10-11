"""Explicit Alembic integration for the database extra.

Xyberos does not build a migration engine. It exposes the configuration and a small wrapper so an
application can run its own Alembic migrations deliberately, at deployment time rather than
implicitly during application startup.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

try:
    from alembic import command
    from alembic.config import Config
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("database", error) from error


def alembic_config(script_location: str | Path, *, url: str) -> Config:
    """Build an Alembic configuration that points at a migration directory and database URL.

    ``sqlite+aiosqlite`` URLs are not usable by Alembic's synchronous engine, so pass the
    synchronous form (``SqliteSettings.sync_url``).

    The URL is escaped rather than passed through. A URL is data: a password containing ``%`` is
    percent-encoded by definition, and a SQLite path may contain one too, so configparser would read
    a bare ``%`` as the start of a substitution. Escaping makes the value survive the round trip —
    configparser resolves ``%%`` back to ``%`` on read — and removes the failure mode that quoting a
    raw value produced: an exception message carrying the whole URL, password included.
    """
    config = Config()
    config.set_main_option("script_location", str(Path(script_location)))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def run_migrations(
    script_location: str | Path,
    *,
    url: str,
    revision: str = "head",
) -> None:
    """Apply migrations synchronously; call it from a thread when serving requests."""
    command.upgrade(alembic_config(script_location, url=url), revision)


async def apply_migrations(
    script_location: str | Path,
    *,
    url: str,
    revision: str = "head",
) -> None:
    """Apply migrations without blocking the event loop."""
    await asyncio.to_thread(run_migrations, script_location, url=url, revision=revision)
