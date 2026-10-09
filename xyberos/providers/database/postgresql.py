from __future__ import annotations

import asyncio
import importlib
import re
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from xyberos.subsystems.database.contracts import (
    DatabaseProvider,
    DatabaseTransaction,
    ExecutionResult,
    Parameters,
)

_DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def adapt_placeholders(statement: str, parameters: Parameters) -> str:
    """Translate portable qmark/named placeholders to psycopg placeholders."""
    if isinstance(parameters, Mapping):
        positional = False
    elif isinstance(parameters, Sequence) and not isinstance(
        parameters,
        (str, bytes, bytearray),
    ):
        positional = True
    else:
        raise TypeError("Database parameters must be a sequence or mapping.")

    result: list[str] = []
    index = 0
    state = "normal"
    dollar_delimiter = ""
    block_comment_depth = 0
    escape_string = False
    while index < len(statement):
        char = statement[index]
        next_char = statement[index + 1] if index + 1 < len(statement) else ""

        if state == "single":
            result.append(char)
            if escape_string and char == "\\" and next_char:
                result.append(next_char)
                index += 2
                continue
            if char == "'" and next_char == "'":
                result.append(next_char)
                index += 2
                continue
            if char == "'":
                state = "normal"
                escape_string = False
            index += 1
            continue

        if state == "double":
            result.append(char)
            if char == '"' and next_char == '"':
                result.append(next_char)
                index += 2
                continue
            if char == '"':
                state = "normal"
            index += 1
            continue

        if state == "line_comment":
            result.append(char)
            if char == "\n":
                state = "normal"
            index += 1
            continue

        if state == "block_comment":
            if char == "/" and next_char == "*":
                result.extend((char, next_char))
                block_comment_depth += 1
                index += 2
                continue
            if char == "*" and next_char == "/":
                result.extend((char, next_char))
                block_comment_depth -= 1
                index += 2
                if block_comment_depth == 0:
                    state = "normal"
                continue
            result.append(char)
            index += 1
            continue

        if state == "dollar_quote":
            if statement.startswith(dollar_delimiter, index):
                result.append(dollar_delimiter)
                index += len(dollar_delimiter)
                state = "normal"
                continue
            result.append(char)
            index += 1
            continue

        if char == "'":
            state = "single"
            escape_string = (
                index > 0
                and statement[index - 1] in ("e", "E")
                and (
                    index < 2
                    or not (
                        statement[index - 2].isalnum()
                        or statement[index - 2] == "_"
                    )
                )
            )
            result.append(char)
            index += 1
        elif char == '"':
            state = "double"
            result.append(char)
            index += 1
        elif char == "-" and next_char == "-":
            state = "line_comment"
            result.extend((char, next_char))
            index += 2
        elif char == "/" and next_char == "*":
            state = "block_comment"
            block_comment_depth = 1
            result.extend((char, next_char))
            index += 2
        elif char == "$":
            match = _DOLLAR_QUOTE.match(statement, index)
            if match:
                dollar_delimiter = match.group()
                state = "dollar_quote"
                result.append(dollar_delimiter)
                index = match.end()
            else:
                result.append(char)
                index += 1
        elif positional and char == "?":
            result.append("%s")
            index += 1
        elif (
            not positional
            and char == ":"
            and next_char != ":"
            and (index == 0 or statement[index - 1] != ":")
        ):
            match = _IDENTIFIER.match(statement, index + 1)
            if match:
                result.append(f"%({match.group()})s")
                index = match.end()
            else:
                result.append(char)
                index += 1
        else:
            result.append(char)
            index += 1

    return "".join(result)


class _PostgreSQLTransaction(DatabaseTransaction):
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def execute(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> ExecutionResult:
        cursor = await self._connection.execute(
            adapt_placeholders(statement, parameters),
            parameters,
        )
        try:
            return ExecutionResult(cursor.rowcount, None)
        finally:
            await cursor.close()

    async def fetch_one(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> dict[str, Any] | None:
        cursor = await self._connection.execute(
            adapt_placeholders(statement, parameters),
            parameters,
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def fetch_all(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> list[dict[str, Any]]:
        cursor = await self._connection.execute(
            adapt_placeholders(statement, parameters),
            parameters,
        )
        try:
            return list(await cursor.fetchall())
        finally:
            await cursor.close()


class PostgreSQLProvider(DatabaseProvider):
    """Async psycopg provider for the portable database contract."""

    def __init__(self) -> None:
        self._connection: Any = None
        self._lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        return "postgresql"

    async def initialize(self, config: Mapping[str, Any]) -> None:
        if self._connection is not None:
            return
        conninfo = config.get("conninfo")
        if not isinstance(conninfo, str) or not conninfo.strip():
            raise ValueError(
                "PostgreSQL provider requires non-empty 'conninfo' configuration."
            )
        connect_timeout = config.get("connect_timeout", 10)
        if (
            not isinstance(connect_timeout, int)
            or isinstance(connect_timeout, bool)
            or connect_timeout < 1
        ):
            raise ValueError(
                "PostgreSQL 'connect_timeout' must be a positive integer."
            )

        try:
            psycopg = importlib.import_module("psycopg")
            rows = importlib.import_module("psycopg.rows")
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL support requires the optional 'postgres' extra. "
                "Install it with: pip install xyberos-minimal[postgres]"
            ) from exc

        self._connection = await psycopg.AsyncConnection.connect(
            conninfo,
            autocommit=True,
            row_factory=rows.dict_row,
            connect_timeout=connect_timeout,
        )

    async def close(self) -> None:
        async with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                await connection.close()

    async def execute(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> ExecutionResult:
        async with self._lock:
            return await _PostgreSQLTransaction(
                self._require_connection()
            ).execute(statement, parameters)

    async def fetch_one(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> dict[str, Any] | None:
        async with self._lock:
            return await _PostgreSQLTransaction(
                self._require_connection()
            ).fetch_one(statement, parameters)

    async def fetch_all(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await _PostgreSQLTransaction(
                self._require_connection()
            ).fetch_all(statement, parameters)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[DatabaseTransaction, None]:
        async with self._lock:
            connection = self._require_connection()
            async with connection.transaction():
                yield _PostgreSQLTransaction(connection)

    def _require_connection(self) -> Any:
        if self._connection is None:
            raise RuntimeError("PostgreSQL provider is not initialized.")
        return self._connection
