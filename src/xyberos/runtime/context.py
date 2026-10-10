"""Context propagation and logging helpers independent of HTTP."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable, Coroutine, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from typing import Any, TypeVar, cast

CORRELATION_ID_KEY = "correlation_id"
DEADLINE_KEY = "deadline"
_context_values: ContextVar[Mapping[str, object] | None] = ContextVar(
    "xyberos_context", default=None
)
T = TypeVar("T")


def get_context() -> dict[str, object]:
    """Return a copy of the current diagnostic context."""
    return dict(_context_values.get() or {})


@contextmanager
def bind_context(**values: object) -> Iterator[None]:
    """Temporarily add diagnostic values to the current context."""
    merged = get_context()
    merged.update(values)
    token = _context_values.set(merged)
    try:
        yield
    finally:
        _context_values.reset(token)


def get_correlation_id() -> str | None:
    """Return the correlation ID bound to the current context, if any."""
    value = (_context_values.get() or {}).get(CORRELATION_ID_KEY)
    return value if isinstance(value, str) else None


@contextmanager
def bind_correlation_id(correlation_id: str) -> Iterator[None]:
    """Bind a correlation ID for the duration of a block."""
    with bind_context(**{CORRELATION_ID_KEY: correlation_id}):
        yield


def get_deadline() -> float | None:
    """Return the absolute cooperative deadline (monotonic seconds) bound to the context."""
    value = (_context_values.get() or {}).get(DEADLINE_KEY)
    return value if isinstance(value, float) else None


@contextmanager
def bind_deadline(deadline: float | None) -> Iterator[None]:
    """Bind or clear the cooperative deadline for the duration of a block."""
    with bind_context(**{DEADLINE_KEY: deadline}):
        yield


def capture_context_runner(
    func: Callable[..., T], /, *args: object, **kwargs: object
) -> Callable[[], T]:
    """Capture the current context and return a runner bound to a copy of it.

    Build the runner in the originating context and invoke it from a thread or other
    custom worker so the current diagnostic context crosses the boundary deliberately.
    """
    context = copy_context()
    return lambda: context.run(func, *args, **kwargs)


def create_task_in_context(
    coroutine: Coroutine[Any, Any, T], *, name: str | None = None
) -> asyncio.Task[T]:
    """Create a task with the caller's context, including on Python 3.10."""
    context = copy_context()
    if sys.version_info >= (3, 11):
        create_task = cast(Callable[..., asyncio.Task[T]], asyncio.create_task)
        return create_task(coroutine, name=name, context=context)
    return context.run(asyncio.create_task, coroutine, name=name)


class ContextLogFilter(logging.Filter):
    """Attach the current Xyberos context as ``xyberos_context`` to a log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.__dict__["xyberos_context"] = get_context()
        return True
