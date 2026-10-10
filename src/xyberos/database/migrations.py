"""Explicit Alembic integration for the database extra.

Xyberos does not build a migration engine. It exposes the configuration and a small wrapper so an
application can run its own Alembic migrations deliberately, at deployment time rather than
implicitly during application startup.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config


def alembic_config(script_location: str | Path, *, url: str) -> Config:
    """Build an Alembic configuration that points at a migration directory and database URL.

    ``sqlite+aiosqlite`` URLs are not usable by Alembic's synchronous engine, so pass the
    synchronous form (``SqliteSettings.sync_url``).
    """
    config = Config()
    config.set_main_option("script_location", str(Path(script_location)))
    config.set_main_option("sqlalchemy.url", url)
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
