"""A database provider written out longhand, so every piece of the contract is visible.

``xyberos.database.contracts.DatabaseProvider`` asks for three things: a transaction context
manager that commits or rolls back, a ``retrying`` helper with a bounded budget, and a ``health``
check. This module implements exactly those, in about a hundred lines, over the same SQLAlchemy
async engine the shipped provider uses.

It is deliberately the shipped provider's *shape*: that shape is the contract, and a walkthrough
that hid it would be teaching a different framework. What the shipped provider adds is settings,
PRAGMA tuning for WAL, a documented error taxonomy, and a factory for dependency injection — all
conveniences on top of this, none of which change what a service may assume.

Swap ``sqlite+aiosqlite`` for another SQLAlchemy async dialect and the same class is a provider for
that database. Services depend on ``DatabaseProvider``, so none of them change.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from xyberos.database import DatabaseProvider, TransactionOperation
from xyberos.errors import (
    DatabaseConnectionError,
    DatabaseError,
    TransactionError,
    TransientDatabaseError,
)

T = TypeVar("T")

#: What SQLite says when another writer holds the lock. Every provider maps its own dialect's
#: equivalent onto `TransientDatabaseError`, and this is the part of the contract retrying() reads.
LOCK_MESSAGES = ("database is locked", "database table is locked", "database schema is locked")


@dataclass(frozen=True)
class ProviderSettings:
    """Where this provider's database lives, and how patient it is about contention."""

    path: Path
    busy_timeout_ms: int = 5000
    retry_attempts: int = 5
    retry_base_delay: float = 0.05

    @property
    def url(self) -> str:
        """Return the SQLAlchemy async URL for this file."""
        return f"sqlite+aiosqlite:///{self.path}"


class SqlProvider:
    """Owns one database file, its engine, and its transaction boundaries."""

    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self._engine: AsyncEngine | None = None

    @property
    def engine(self) -> AsyncEngine:
        """Return the started engine, or report that the provider was never started."""
        if self._engine is None:
            raise DatabaseConnectionError("the provider has not been started")
        return self._engine

    async def start(self) -> SqlProvider:
        """Create the engine, wait up to the busy timeout for locks, and check connectivity."""
        settings = self.settings
        settings.path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(settings.url)
        event.listen(engine.sync_engine, "connect", _busy_timeout_hook(settings.busy_timeout_ms))
        self._engine = engine
        try:
            await self.health()
        except DatabaseError:
            # A provider that fails its own readiness check must not leave an engine behind.
            self._engine = None
            await engine.dispose()
            raise
        return self

    async def aclose(self) -> None:
        """Release the engine and its pooled connections."""
        engine, self._engine = self._engine, None
        if engine is not None:
            await engine.dispose()

    async def health(self) -> None:
        """Run a trivial query, so readiness reflects connectivity rather than intent."""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            raise DatabaseConnectionError(f"health check failed: {error}") from error

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
        """Run an idempotent operation, retrying only the documented transient failure.

        The budget is bounded and the delay grows linearly: a provider that waited forever would
        turn a lock into an outage, which is the failure the contract exists to prevent.
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


async def open_provider(path: Path) -> SqlProvider:
    """Create, start, and return a provider the caller owns and closes."""
    return await SqlProvider(ProviderSettings(path=path)).start()


def _busy_timeout_hook(milliseconds: int) -> Any:
    """Return the connect hook that makes SQLite wait for a writer instead of failing at once."""

    def hook(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA busy_timeout = {int(milliseconds)}")
        cursor.close()

    return hook


async def _rollback_quietly(transaction: Any) -> None:
    """Roll back, ignoring a failure that would mask the error being raised."""
    try:
        await transaction.rollback()
    except Exception:  # noqa: BLE001 - the original error is the one worth reporting
        pass


def _transaction_error(error: SQLAlchemyError) -> DatabaseError:
    """Map a commit failure onto the contract's taxonomy."""
    if _is_lock_contention(error):
        return TransientDatabaseError(f"the transaction could not commit: {error}")
    return TransactionError(f"the transaction could not commit: {error}")


def _is_lock_contention(error: BaseException) -> bool:
    """Whether an error is the documented transient write contention."""
    if isinstance(error, TransientDatabaseError):
        return True
    if isinstance(error, OperationalError):
        message = str(getattr(error, "orig", error)).lower()
        return any(fragment in message for fragment in LOCK_MESSAGES)
    return False


class CommitsOnFailure:
    """A provider that commits the work a failed transaction should have rolled back.

    This is the mistake the contract exists to catch, and nothing about it looks wrong at a call
    site: the context manager yields a connection and the work is written. The difference appears
    only when the body raises, which is what the conformance suite does.
    """

    def __init__(self, inner: DatabaseProvider) -> None:
        self._inner = inner

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self._inner.transaction() as connection:
            try:
                yield connection
            except Exception:
                await connection.commit()
                raise

    def retrying(
        self,
        operation: TransactionOperation[T],
        *,
        attempts: int | None = None,
        base_delay: float | None = None,
    ) -> object:
        return self._inner.retrying(operation, attempts=attempts, base_delay=base_delay)

    async def health(self) -> None:
        await self._inner.health()
