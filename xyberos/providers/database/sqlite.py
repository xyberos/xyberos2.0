from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from xyberos.subsystems.database.contracts import (
    DatabaseProvider,
    DatabaseTransaction,
    ExecutionResult,
    Parameters,
)


class _SQLiteTransaction(DatabaseTransaction):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    async def execute(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> ExecutionResult:
        return await asyncio.to_thread(
            _execute_sync,
            self._connection,
            statement,
            parameters,
        )

    async def fetch_one(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> dict[str, Any] | None:
        rows = await asyncio.to_thread(
            _fetch_sync,
            self._connection,
            statement,
            parameters,
            True,
        )
        return rows[0] if rows else None

    async def fetch_all(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            _fetch_sync,
            self._connection,
            statement,
            parameters,
            False,
        )


def _execute_sync(
    connection: sqlite3.Connection,
    statement: str,
    parameters: Parameters,
) -> ExecutionResult:
    cursor = connection.execute(statement, parameters)
    result = ExecutionResult(cursor.rowcount, cursor.lastrowid)
    cursor.close()
    return result


def _fetch_sync(
    connection: sqlite3.Connection,
    statement: str,
    parameters: Parameters,
    one: bool,
) -> list[dict[str, Any]]:
    cursor = connection.execute(statement, parameters)
    rows = cursor.fetchmany(1) if one else cursor.fetchall()
    result = [dict(row) for row in rows]
    cursor.close()
    return result


class SQLiteProvider(DatabaseProvider):
    """Async SQLite provider using a serialized connection and worker threads."""

    def __init__(self) -> None:
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        return "sqlite"

    async def initialize(self, config: Mapping[str, Any]) -> None:
        if self._connection is not None:
            return

        path_value = config.get("path", "./data/app.db")
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("SQLite 'path' must be a non-empty string.")
        busy_timeout_ms = config.get("busy_timeout_ms", 30_000)
        if not isinstance(busy_timeout_ms, int) or isinstance(busy_timeout_ms, bool):
            raise ValueError("SQLite 'busy_timeout_ms' must be a non-negative integer.")
        if busy_timeout_ms < 0:
            raise ValueError("SQLite 'busy_timeout_ms' must be a non-negative integer.")
        journal_mode = config.get("journal_mode", "WAL")
        if not isinstance(journal_mode, str):
            raise ValueError("SQLite 'journal_mode' must be a string.")

        if path_value != ":memory:":
            Path(path_value).expanduser().resolve().parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        connection = await asyncio.to_thread(
            sqlite3.connect,
            path_value,
            timeout=busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        try:
            await asyncio.to_thread(
                connection.execute,
                "PRAGMA foreign_keys = ON",
            )
            await asyncio.to_thread(
                connection.execute,
                f"PRAGMA busy_timeout = {busy_timeout_ms}",
            )
            if path_value != ":memory:":
                if journal_mode.upper() not in {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}:
                    raise ValueError(f"Unsupported SQLite journal mode: {journal_mode}")
                await asyncio.to_thread(
                    connection.execute,
                    f"PRAGMA journal_mode = {journal_mode.upper()}",
                )
        except BaseException:
            await asyncio.to_thread(connection.close)
            raise
        self._connection = connection

    async def close(self) -> None:
        async with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                await asyncio.to_thread(connection.close)

    async def execute(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> ExecutionResult:
        async with self._lock:
            return await asyncio.to_thread(
                _execute_sync,
                self._require_connection(),
                statement,
                parameters,
            )

    async def fetch_one(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> dict[str, Any] | None:
        async with self._lock:
            rows = await asyncio.to_thread(
                _fetch_sync,
                self._require_connection(),
                statement,
                parameters,
                True,
            )
            return rows[0] if rows else None

    async def fetch_all(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(
                _fetch_sync,
                self._require_connection(),
                statement,
                parameters,
                False,
            )

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[DatabaseTransaction, None]:
        async with self._lock:
            connection = self._require_connection()
            await asyncio.to_thread(connection.execute, "BEGIN")
            try:
                yield _SQLiteTransaction(connection)
            except BaseException:
                await asyncio.to_thread(connection.rollback)
                raise
            else:
                await asyncio.to_thread(connection.commit)

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLite provider is not initialized.")
        return self._connection
