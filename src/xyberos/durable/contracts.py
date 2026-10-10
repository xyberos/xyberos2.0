"""Public contracts of the durable executor.

The clock here is a *wall* clock, and that is a deliberate difference from the in-process engine's
monotonic clock: a lease or a deadline that has to survive a restart cannot be expressed in a
monotonic reading, because the reading starts over with the process.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Protocol


class WallClock(Protocol):
    """The time source the journal uses for timestamps, leases, and deadlines."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...

    async def sleep(self, delay: float) -> None:
        """Wait for ``delay`` seconds of this clock's time."""
        ...


class SystemWallClock:
    """The default wall clock: UTC timestamps and real sleeping."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, delay: float) -> None:
        await asyncio.sleep(delay)


def utc_now() -> datetime:
    """Return the current UTC time, used when no clock was injected."""
    return datetime.now(timezone.utc)
