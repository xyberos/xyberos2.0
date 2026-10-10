"""A single-file SQLite provider built on SQLAlchemy Core and the ``aiosqlite`` driver.

Xyberos owns the file path, connection PRAGMAs, transaction boundaries, and a bounded retry
budget for write contention. SQLAlchemy owns the driver integration; applications keep using
Core statements and do not need ORM sessions.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncTransaction,
    create_async_engine,
)

from xyberos.database.contracts import TransactionOperation
from xyberos.errors import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseError,
    TransactionError,
    TransientDatabaseError,
)

T = TypeVar("T")

_JOURNAL_MODES = frozenset({"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY", "OFF"})
_SYNCHRONOUS_MODES = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})
_LOCK_MESSAGES = ("database is locked", "database table is locked", "database schema is locked")


@dataclass(frozen=True)
class SqliteSettings:
    """Explicit, configurable defaults for one SQLite database file.

    ``journal_mode="WAL"`` with ``synchronous="NORMAL"`` is a performance/durability trade-off,
    not an unconditional guarantee: set ``synchronous="FULL"`` when a committed transaction must
    survive an operating-system crash. Keep the application database and the durable journal in
    separate files.
    """

    path: str | Path = "var/app.db"
    echo: bool = False
    foreign_keys: bool = True
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    busy_timeout_ms: int = 5000
    retry_attempts: int = 5
    retry_base_delay: float = 0.05

    def __post_init__(self) -> None:
        journal_mode = self.journal_mode.upper()
        if journal_mode not in _JOURNAL_MODES:
            supported = ", ".join(sorted(_JOURNAL_MODES))
            raise DatabaseConfigurationError(
                f"unsupported journal_mode {self.journal_mode!r}; expected one of: {supported}"
            )
        object.__setattr__(self, "journal_mode", journal_mode)
        if self.in_memory and journal_mode == "WAL":
            raise DatabaseConfigurationError(
                "journal_mode WAL is not supported for an in-memory SQLite database"
            )
        synchronous = self.synchronous.upper()
        if synchronous not in _SYNCHRONOUS_MODES:
            supported = ", ".join(sorted(_SYNCHRONOUS_MODES))
            raise DatabaseConfigurationError(
                f"unsupported synchronous mode {self.synchronous!r}; expected one of: {supported}"
            )
        object.__setattr__(self, "synchronous", synchronous)
        if self.busy_timeout_ms < 0:
            raise DatabaseConfigurationError("busy_timeout_ms must not be negative")
        if self.retry_attempts < 1:
            raise DatabaseConfigurationError("retry_attempts must be at least 1")
        if self.retry_base_delay < 0:
            raise DatabaseConfigurationError("retry_base_delay must not be negative")

    @property
    def in_memory(self) -> bool:
        """Whether the settings describe a non-persistent in-memory database."""
        return str(self.path) == ":memory:"

    @property
    def file_path(self) -> Path | None:
        """The resolved database file, or ``None`` for an in-memory database."""
        if self.in_memory:
            return None
        return Path(self._location)

    @property
    def url(self) -> str:
        """The async SQLAlchemy URL used by the provider."""
        return f"sqlite+aiosqlite:///{self._location}"

    @property
    def sync_url(self) -> str:
        """The synchronous SQLAlchemy URL used by Alembic migrations."""
        return f"sqlite:///{self._location}"

    @property
    def _location(self) -> str:
        if self.in_memory:
            return ":memory:"
        path = Path(self.path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.as_posix()


class SqliteDatabase:
    """Owns one SQLite file, its engine, and its transaction boundaries."""

    def __init__(self, settings: SqliteSettings | None = None) -> None:
        self.settings = SqliteSettings() if settings is None else settings
        self._engine: AsyncEngine | None = None

    @property
    def engine(self) -> AsyncEngine:
        """Return the started engine, or report that the provider was never started."""
        if self._engine is None:
            raise DatabaseConnectionError("the database has not been started")
        return self._engine

    async def start(self) -> None:
        """Create the engine, install connection PRAGMAs, and verify connectivity."""
        if self._engine is not None:
            return
        file_path = self.settings.file_path
        if file_path is not None:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(self.settings.url, echo=self.settings.echo)
        _install_pragmas(engine, self.settings)
        self._engine = engine
        try:
            await self.health()
        except DatabaseError:
            self._engine = None
            await engine.dispose()
            raise

    async def aclose(self) -> None:
        """Release the engine and its pooled connections."""
        engine, self._engine = self._engine, None
        if engine is not None:
            await engine.dispose()

    async def health(self) -> None:
        """Run a trivial query so readiness reflects real connectivity."""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            raise DatabaseConnectionError(f"database health check failed: {error}") from error

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """Open a short-lived transaction, committing on success and rolling back on error."""
        async with self.engine.connect() as connection:
            transaction = await connection.begin()
            try:
                yield connection
            except BaseException:
                await _rollback_quietly(transaction)
                raise
            try:
                await transaction.commit()
            except SQLAlchemyError as error:
                await _rollback_quietly(transaction)
                raise _transaction_error(error) from error

    async def retrying(
        self,
        operation: TransactionOperation[T],
        *,
        attempts: int | None = None,
        base_delay: float | None = None,
    ) -> T:
        """Retry an idempotent operation while SQLite reports transient write contention.

        The budget is bounded and the delay grows linearly, so a blocked writer fails with
        ``TransientDatabaseError`` rather than waiting indefinitely.
        """
        max_attempts = self.settings.retry_attempts if attempts is None else attempts
        delay = self.settings.retry_base_delay if base_delay is None else base_delay
        for attempt in range(1, max_attempts + 1):
            try:
                async with self.transaction() as connection:
                    return await operation(connection)
            except Exception as error:
                if not _is_lock_contention(error):
                    raise
                if attempt >= max_attempts:
                    raise TransientDatabaseError(
                        f"the database stayed locked after {max_attempts} attempt(s)"
                    ) from error
                await asyncio.sleep(delay * attempt)
        raise AssertionError("unreachable: the retry loop always returns or raises")


async def open_database(settings: SqliteSettings | None = None) -> SqliteDatabase:
    """Create, start, and return a database that the caller owns and closes."""
    database = SqliteDatabase(settings)
    await database.start()
    return database


def sqlite_provider(
    settings: SqliteSettings | None = None,
) -> Callable[[], Awaitable[SqliteDatabase]]:
    """Return a dependency-free factory suitable for ``App.provide(..., eager=True)``."""

    async def factory() -> SqliteDatabase:
        return await open_database(settings)

    return factory


def _install_pragmas(engine: AsyncEngine, settings: SqliteSettings) -> None:
    statements = [f"PRAGMA busy_timeout={int(settings.busy_timeout_ms)}"]
    if settings.foreign_keys:
        statements.append("PRAGMA foreign_keys=ON")
    if not settings.in_memory:
        statements.append(f"PRAGMA journal_mode={settings.journal_mode}")
    statements.append(f"PRAGMA synchronous={settings.synchronous}")

    @event.listens_for(engine.sync_engine, "connect")
    def _apply_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for statement in statements:
                cursor.execute(statement)
        finally:
            cursor.close()


async def _rollback_quietly(transaction: AsyncTransaction) -> None:
    try:
        await transaction.rollback()
    except SQLAlchemyError:
        pass


def _transaction_error(error: SQLAlchemyError) -> DatabaseError:
    if _is_lock_contention(error):
        return TransientDatabaseError(f"the transaction could not commit: {error}")
    return TransactionError(f"the transaction could not commit: {error}")


def _is_lock_contention(error: BaseException) -> bool:
    if isinstance(error, TransientDatabaseError):
        return True
    if isinstance(error, OperationalError):
        message = str(getattr(error, "orig", error)).lower()
        return any(fragment in message for fragment in _LOCK_MESSAGES)
    return False
