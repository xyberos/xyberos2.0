"""Deterministic doubles for durable-execution tests.

Lease expiry, heartbeats, and retry scheduling are timing behavior, so they are tested with a clock
that only moves when a test moves it. A virtual sleeper waits until ``advance`` reaches its
deadline, which is what lets a test sit inside a running step and decide what happens to the lease
and to cancellation next.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from xyberos.durable.contracts import utc_now
from xyberos.durable.journal import Journal, to_iso
from xyberos.durable.models import ActivityPolicy


async def expire_leases(journal: Journal) -> int:
    """Backdate every live lease so recovery sees it as expired; return how many were changed.

    This is a virtual clock for a *separate* process. A subprocess that is killed cannot be given a
    test clock, so a test that has to prove what happens after its lease runs out backdates the
    lease row instead of sleeping. The effect is identical to the passage of time with no
    heartbeat, and it makes the assertion deterministic rather than timing-dependent.

    Deleting the row would be a different test: expiry is the case where the previous owner is
    unknown rather than absent, and the fencing token must still be honoured.
    """
    past = to_iso(utc_now() - timedelta(days=1))
    async with journal.database.transaction() as connection:
        result = await connection.execute(
            text("UPDATE worker_leases SET expires_at = :past WHERE expires_at > :past"),
            {"past": past},
        )
        return int(result.rowcount)


@dataclass
class ManualWallClock:
    """A wall clock that only advances when a test advances it."""

    start: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    _now: datetime = field(init=False, repr=False)
    _waiters: list[tuple[datetime, asyncio.Future[None]]] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._now = self.start

    def now(self) -> datetime:
        """Return the current virtual time."""
        return self._now

    async def sleep(self, delay: float) -> None:
        """Wait until virtual time reaches ``now + delay``."""
        target = self._now + timedelta(seconds=delay)
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append((target, waiter))
        try:
            await waiter
        except asyncio.CancelledError:
            self._waiters = [entry for entry in self._waiters if entry[1] is not waiter]
            raise

    @property
    def sleepers(self) -> int:
        """How many virtual sleeps are waiting right now."""
        return len(self._waiters)

    def advance(self, seconds: float) -> datetime:
        """Move virtual time forward and wake every sleeper whose deadline has passed."""
        self._now += timedelta(seconds=seconds)
        remaining: list[tuple[datetime, asyncio.Future[None]]] = []
        for target, waiter in self._waiters:
            if target <= self._now:
                if not waiter.done():
                    waiter.set_result(None)
            else:
                remaining.append((target, waiter))
        self._waiters = remaining
        return self._now

    async def wait_for_sleepers(self, count: int = 1, *, rounds: int = 1000) -> None:
        """Yield until ``count`` sleeps are registered, or fail if they never arrive."""
        for _ in range(rounds):
            if len(self._waiters) >= count:
                return
            await asyncio.sleep(0)
        raise AssertionError(
            f"only {len(self._waiters)} virtual sleeper(s) registered after {rounds} rounds"
        )


def idempotent_activity() -> ActivityPolicy:
    """An activity policy that says a step is safe to run again."""
    return ActivityPolicy(idempotent=True)
