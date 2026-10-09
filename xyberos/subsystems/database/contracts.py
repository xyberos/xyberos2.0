from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from xyberos.kernel.contracts import Provider

Parameters = Sequence[Any] | Mapping[str, Any]


@dataclass(frozen=True)
class ExecutionResult:
    rowcount: int
    lastrowid: int | None = None


class DatabaseTransaction(ABC):
    @abstractmethod
    async def execute(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> ExecutionResult:
        """Execute a parameterized statement inside the active transaction."""

    @abstractmethod
    async def fetch_one(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> dict[str, Any] | None:
        """Fetch one row from the active transaction."""

    @abstractmethod
    async def fetch_all(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> list[dict[str, Any]]:
        """Fetch all rows from the active transaction."""


class Database(ABC):
    @abstractmethod
    async def execute(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> ExecutionResult:
        """Execute a parameterized statement."""

    @abstractmethod
    async def fetch_one(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> dict[str, Any] | None:
        """Fetch one row."""

    @abstractmethod
    async def fetch_all(
        self,
        statement: str,
        parameters: Parameters = (),
    ) -> list[dict[str, Any]]:
        """Fetch all rows."""

    @abstractmethod
    def transaction(self) -> AbstractAsyncContextManager[DatabaseTransaction]:
        """Return an async transaction context manager."""


class DatabaseProvider(Provider, Database):
    @abstractmethod
    async def initialize(self, config: Mapping[str, Any]) -> None:
        """Open and configure provider resources."""

    @abstractmethod
    async def close(self) -> None:
        """Close provider resources."""
