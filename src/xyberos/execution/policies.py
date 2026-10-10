"""Execution policies shared by direct calls and workflow steps.

Retries, backoff, clocks, deadlines, and cancellation are the whole contract here. Nothing in
this module depends on an HTTP, database, AI, or durable capability.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from random import Random
from typing import Protocol

from xyberos.errors import (
    TransientError,
    WorkflowCancelledError,
    WorkflowTimeoutError,
    WorkflowValidationError,
)

DEFAULT_LOGGER_NAME = "xyberos.workflow"


def seconds(value: float) -> float:
    """Return ``value`` seconds, for readable policy arguments."""
    return float(value)


def milliseconds(value: float) -> float:
    """Return ``value`` milliseconds expressed in seconds."""
    return float(value) / 1000.0


def minutes(value: float) -> float:
    """Return ``value`` minutes expressed in seconds."""
    return float(value) * 60.0


@dataclass(frozen=True)
class Backoff:
    """Deterministic backoff delays with optional jitter.

    The delay before the attempt after ``attempt`` (1-based) is
    ``initial * multiplier ** (attempt - 1)``, capped at ``max_delay``. ``jitter`` is the fraction
    of that delay randomisation may remove, so a delay is never longer than the computed value and
    never shorter than ``1 - jitter`` of it. Jitter draws from the executor's random source, which
    tests seed to keep retry timing deterministic.
    """

    initial: float = 0.1
    multiplier: float = 2.0
    max_delay: float = 5.0
    jitter: float = 0.0

    def __post_init__(self) -> None:
        if self.initial < 0:
            raise WorkflowValidationError("backoff initial delay cannot be negative")
        if self.multiplier < 1:
            raise WorkflowValidationError("backoff multiplier must be at least 1")
        if self.max_delay < 0:
            raise WorkflowValidationError("backoff max_delay cannot be negative")
        if not 0.0 <= self.jitter <= 1.0:
            raise WorkflowValidationError("backoff jitter must be between 0 and 1")

    def delay_for(self, attempt: int, *, random: Random) -> float:
        """Return the delay to wait after ``attempt`` (1-based) failed."""
        if attempt < 1:
            raise WorkflowValidationError("attempt numbers start at 1")
        delay = min(self.initial * self.multiplier ** (attempt - 1), self.max_delay)
        if self.jitter:
            delay *= 1.0 - self.jitter * random.random()
        return max(delay, 0.0)


@dataclass(frozen=True)
class Retry:
    """A bounded, policy-driven retry budget for one step.

    ``max_attempts`` counts the first try, so ``max_attempts=1`` means no retrying. ``retry_on``
    selects the failures that may be retried; by default only
    :class:`~xyberos.errors.TransientError` and its subclasses qualify.
    """

    max_attempts: int = 1
    retry_on: tuple[type[BaseException], ...] = (TransientError,)
    backoff: Backoff = Backoff()

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise WorkflowValidationError("retry max_attempts must be at least 1")
        if not self.retry_on:
            raise WorkflowValidationError("retry retry_on must name at least one exception type")
        for candidate in self.retry_on:
            if not (isinstance(candidate, type) and issubclass(candidate, BaseException)):
                raise WorkflowValidationError(
                    f"retry retry_on entries must be exception types, got {candidate!r}"
                )

    def allows(self, error: BaseException) -> bool:
        """Return whether this policy may retry ``error``."""
        return isinstance(error, self.retry_on)


class Clock(Protocol):
    """The time source an executor uses for deadlines and backoff delays."""

    def monotonic(self) -> float:
        """Return the current monotonic time in seconds."""
        ...

    async def sleep(self, delay: float) -> None:
        """Wait for ``delay`` seconds of this clock's time."""
        ...


class SystemClock:
    """The default clock: monotonic wall time and real sleeping."""

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, delay: float) -> None:
        await asyncio.sleep(delay)


class CancellationToken:
    """A cooperative cancellation signal for one workflow execution.

    The token is bound to the event loop that awaits :meth:`wait`, so :meth:`cancel` is not
    thread-safe: request cancellation from the same loop. Cancelling a parent token cancels every
    token derived from it, which is how a step's attempt stops when the whole run does.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._reason: str | None = None
        self._waiters: asyncio.Event | None = None
        self._children: list[CancellationToken] = []

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._cancelled

    @property
    def reason(self) -> str | None:
        """The reason given to :meth:`cancel`, if any."""
        return self._reason

    def cancel(self, reason: str | None = None) -> None:
        """Request cancellation, keeping the first reason that was given."""
        if self._cancelled:
            return
        self._cancelled = True
        self._reason = reason
        if self._waiters is not None:
            self._waiters.set()
        for child in tuple(self._children):
            child.cancel(reason)

    def child(self) -> CancellationToken:
        """Return a token that is cancelled whenever this one is."""
        child = CancellationToken()
        if self._cancelled:
            child.cancel(self._reason)
            return child
        self._children.append(child)
        return child

    async def wait(self) -> None:
        """Return once cancellation has been requested."""
        if self._cancelled:
            return
        if self._waiters is None:
            self._waiters = asyncio.Event()
        await self._waiters.wait()


def _default_logger() -> logging.Logger:
    return logging.getLogger(DEFAULT_LOGGER_NAME)


@dataclass(frozen=True)
class StepContext:
    """Everything a step function is given besides its declared input.

    The context is the only channel for execution metadata: the attempt number, the absolute
    deadline, cooperative cancellation, and a logger already named for this workflow and step.
    """

    workflow: str
    version: str
    step: str
    attempt: int
    cancellation: CancellationToken
    clock: Clock
    deadline: float | None = None
    correlation_id: str | None = None
    logger: logging.Logger = field(default_factory=_default_logger)

    def remaining(self) -> float | None:
        """Return the seconds left before the deadline, or ``None`` when unbounded."""
        if self.deadline is None:
            return None
        return max(self.deadline - self.clock.monotonic(), 0.0)

    def expired(self) -> bool:
        """Whether the deadline has been reached."""
        remaining = self.remaining()
        return remaining is not None and remaining <= 0.0

    def check(self) -> None:
        """Raise if cancellation was requested or the deadline has passed.

        Long-running steps should call this between units of work to cooperate with cancellation.
        """
        if self.cancellation.cancelled:
            reason = self.cancellation.reason or "cancellation requested"
            raise WorkflowCancelledError(
                f"workflow {self.workflow!r} was cancelled before step {self.step!r} ({reason})",
                workflow=self.workflow,
                step=self.step,
            )
        if self.expired():
            raise WorkflowTimeoutError(
                f"workflow {self.workflow!r} exceeded its deadline at step {self.step!r}",
                workflow=self.workflow,
                step=self.step,
            )
