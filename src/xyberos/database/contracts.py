"""Database provider contracts consumed by services.

The protocol below is the boundary a service depends on. It deliberately exposes transaction
boundaries and a bounded retry helper, not ORM sessions, so a different provider can replace
SQLite without rewriting services.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, TypeAlias, TypeVar

try:
    from sqlalchemy.ext.asyncio import AsyncConnection
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("database", error) from error

T = TypeVar("T")

TransactionOperation: TypeAlias = Callable[[AsyncConnection], Awaitable[T]]


class DatabaseProvider(Protocol):
    """The minimal database surface a service may depend on."""

    def transaction(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Open a short-lived transaction, committing on success and rolling back on error."""
        ...

    def retrying(
        self,
        operation: TransactionOperation[T],
        *,
        attempts: int | None = None,
        base_delay: float | None = None,
    ) -> Awaitable[T]:
        """Run an idempotent operation with a bounded retry budget for write contention."""
        ...

    async def health(self) -> None:
        """Raise a ``DatabaseError`` when the database cannot serve a trivial query."""
        ...
