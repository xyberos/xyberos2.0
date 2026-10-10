"""Deterministic doubles for durable-execution tests.

Lease expiry and retry scheduling are timing behavior, so they are tested with a clock that only
moves when a test moves it. Nothing here needs a service, a thread, or a sleep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from xyberos.durable.models import ActivityPolicy


@dataclass
class ManualWallClock:
    """A wall clock that only advances when a test advances it."""

    start: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    _now: datetime = field(init=False, repr=False)
    sleepers: list[float] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._now = self.start

    def now(self) -> datetime:
        """Return the current virtual time."""
        return self._now

    async def sleep(self, delay: float) -> None:
        """Advance virtual time instead of waiting, so a polling loop cannot hang a test."""
        self.sleepers.append(delay)
        self.advance(delay)

    def advance(self, seconds: float) -> datetime:
        """Move virtual time forward and return the new instant."""
        self._now += timedelta(seconds=seconds)
        return self._now


def idempotent_activity() -> ActivityPolicy:
    """An activity policy that says a step is safe to run again."""
    return ActivityPolicy(idempotent=True)
