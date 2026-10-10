"""Test utilities for the database extra."""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from xyberos.database.sqlite import SqliteDatabase, SqliteSettings, open_database


@asynccontextmanager
async def temporary_database(
    *,
    directory: Path | None = None,
    journal_mode: str = "WAL",
    synchronous: str = "NORMAL",
    busy_timeout_ms: int = 5000,
) -> AsyncIterator[SqliteDatabase]:
    """Yield a started database backed by a real temporary file, then close and remove it.

    A real file is used rather than an in-memory database so that WAL mode, file locking, and
    restart behavior are exercised exactly as they are in production.
    """
    if directory is not None:
        database = await open_database(
            SqliteSettings(
                path=directory / "test.db",
                journal_mode=journal_mode,
                synchronous=synchronous,
                busy_timeout_ms=busy_timeout_ms,
            )
        )
        try:
            yield database
        finally:
            await database.aclose()
        return

    with tempfile.TemporaryDirectory(prefix="xyberos-test-") as temporary:
        database = await open_database(
            SqliteSettings(
                path=Path(temporary) / "test.db",
                journal_mode=journal_mode,
                synchronous=synchronous,
                busy_timeout_ms=busy_timeout_ms,
            )
        )
        try:
            yield database
        finally:
            await database.aclose()
