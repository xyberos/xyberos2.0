"""Deterministic test doubles for workflow code.

Nothing here touches the wall clock or a network: :class:`ManualClock` makes time something the
test moves, and :class:`FakeExternalService` plays a scripted sequence of replies so latency, rate
limiting, transient failures, malformed responses, and cancellation are all reproducible.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeVar

from xyberos.errors import TransientError, XyberosError
from xyberos.execution.policies import Clock, SystemClock

T = TypeVar("T")

MALFORMED_PAYLOAD: Mapping[str, object] = MappingProxyType(
    {"error": "unexpected response shape", "missing": ("data",)}
)
"""A payload that does not match a documented response shape."""


def pending_tasks() -> list[asyncio.Task[object]]:
    """Return the tasks still pending besides the calling one.

    Use it to assert that an execution left nothing behind: the executor must never return while a
    task it created is still running.
    """
    current = asyncio.current_task()
    return [task for task in asyncio.all_tasks() if task is not current]


class RateLimitError(TransientError):
    """Raised when a service asks the caller to slow down. Retryable by default."""


class TransientServiceError(TransientError):
    """Raised when a remote call failed in a way worth retrying. Retryable by default."""


class MalformedResponseError(XyberosError):
    """Raised when a response does not match the documented shape.

    It is deliberately not a :class:`~xyberos.errors.TransientError`: a contract violation is a code
    or version problem, so retrying it has to be an explicit policy decision.
    """


class ManualClock:
    """A virtual clock whose time moves only when the test moves it.

    ``sleep`` registers a sleeper instead of blocking, so a test can put the executor in the middle
    of a deadline and then decide when that deadline passes. That keeps timeout and backoff
    assertions free of wall-clock sleeps.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)
        self._sleepers: list[tuple[float, asyncio.Event]] = []
        self._sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._now

    async def sleep(self, delay: float) -> None:
        target = self._now + max(delay, 0.0)
        event = asyncio.Event()
        self._sleeps.append(max(delay, 0.0))
        self._sleepers.append((target, event))
        try:
            await event.wait()
        finally:
            self._sleepers = [item for item in self._sleepers if item[1] is not event]

    @property
    def pending(self) -> tuple[float, ...]:
        """Absolute wake-up times of the registered sleepers, in registration order."""
        return tuple(target for target, _ in self._sleepers)

    @property
    def sleeps(self) -> tuple[float, ...]:
        """Every delay that has been requested so far, in order.

        Retry tests assert on this to prove the backoff sequence without inspecting internals.
        """
        return tuple(self._sleeps)

    def advance(self, delta: float) -> None:
        """Move time forward, waking every sleeper whose wake-up time has been reached."""
        self._now += max(delta, 0.0)
        self._wake()

    def advance_to_next(self) -> float | None:
        """Jump to the earliest pending wake-up and return how much time that skipped."""
        if not self._sleepers:
            return None
        target = min(candidate for candidate, _ in self._sleepers)
        skipped = max(target - self._now, 0.0)
        self._now = max(self._now, target)
        self._wake()
        return skipped

    async def wait_for_sleepers(self, count: int = 1, *, ticks: int = 200) -> None:
        """Yield until at least ``count`` sleepers are registered.

        Tests use this to reach the moment the executor is waiting on a deadline before moving time
        forward, so nothing depends on an arbitrary wall-clock sleep.
        """
        for _ in range(ticks):
            if len(self._sleepers) >= count:
                return
            await asyncio.sleep(0)
        raise AssertionError(f"the clock never reached {count} pending sleeper(s)")

    async def drive(self, task: asyncio.Task[T], *, rounds: int = 1000, settle: int = 8) -> T:
        """Run ``task`` to completion, advancing virtual time when nothing else can progress.

        Each round yields to the event loop ``settle`` times first, so nested tasks reach their
        first wait before time moves, then jumps virtual time to the earliest registered wake-up.
        Time may overshoot a deadline that is still being torn down, so use
        :meth:`wait_for_sleepers` with :meth:`advance` whenever a test asserts exactly how much
        time passed; this method only decides *when* time passes.
        """
        for _ in range(rounds):
            for _ in range(settle):
                await asyncio.sleep(0)
                if task.done():
                    return task.result()
            self.advance_to_next()
        if task.done():
            return task.result()
        raise AssertionError(f"the task did not finish within {rounds} rounds of virtual time")

    def _wake(self) -> None:
        for target, event in tuple(self._sleepers):
            if target <= self._now:
                event.set()


@dataclass(frozen=True)
class Reply:
    """One scripted response from :class:`FakeExternalService`."""

    value: object = None
    error: BaseException | None = None
    latency: float = 0.0

    @classmethod
    def ok(cls, value: object = None, *, latency: float = 0.0) -> Reply:
        """Return a successful reply."""
        return cls(value=value, latency=latency)

    @classmethod
    def slow(cls, latency: float) -> Reply:
        """Return a successful reply that waits ``latency`` seconds of the injected clock."""
        return cls(latency=latency)

    @classmethod
    def failing(cls, error: BaseException, *, latency: float = 0.0) -> Reply:
        """Return a reply that raises ``error``."""
        return cls(error=error, latency=latency)

    @classmethod
    def rate_limited(cls, *, latency: float = 0.0) -> Reply:
        """Return a reply that raises :class:`RateLimitError`."""
        return cls(
            error=RateLimitError("the fake service asked the caller to slow down"),
            latency=latency,
        )

    @classmethod
    def transient(cls, *, latency: float = 0.0) -> Reply:
        """Return a reply that raises :class:`TransientServiceError`."""
        return cls(
            error=TransientServiceError("the fake service failed transiently"),
            latency=latency,
        )

    @classmethod
    def malformed(cls, *, latency: float = 0.0) -> Reply:
        """Return a payload that does not match the documented shape."""
        return cls(value=MALFORMED_PAYLOAD, latency=latency)


class FakeExternalService:
    """A deterministic stand-in for a remote service.

    Replies play in order and the final reply repeats once the script is exhausted, so "always rate
    limited" and "fails twice, then succeeds" are both one line. Latency waits on the injected
    clock, which means a :class:`ManualClock` keeps a slow call under the test's control and a
    cancelled call records that it observed cancellation.
    """

    def __init__(self, script: Sequence[Reply] = (), *, clock: Clock | None = None) -> None:
        self._script = tuple(script) or (Reply.ok(),)
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._calls = 0
        self._cancellations = 0
        self.last_call: tuple[tuple[object, ...], dict[str, object]] | None = None

    @property
    def calls(self) -> int:
        """How many times :meth:`call` has been invoked."""
        return self._calls

    @property
    def observed_cancellations(self) -> int:
        """How many calls observed cancellation while they were waiting."""
        return self._cancellations

    def reset(self) -> None:
        """Forget the counters and the last request so one fake can serve several scenarios."""
        self._calls = 0
        self._cancellations = 0
        self.last_call = None

    async def call(self, *args: object, **kwargs: object) -> object:
        """Play the next scripted reply, honouring latency and cancellation."""
        reply = self._script[min(self._calls, len(self._script) - 1)]
        self._calls += 1
        self.last_call = (args, dict(kwargs))
        if reply.latency:
            try:
                await self._clock.sleep(reply.latency)
            except asyncio.CancelledError:
                self._cancellations += 1
                raise
        if reply.error is not None:
            raise reply.error
        return reply.value
