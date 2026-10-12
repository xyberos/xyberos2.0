"""Lesson 14 — the errors you will meet, and how to read them.

Every error Xyberos raises derives from ``XyberosError``, and each one names the thing you have to
fix rather than the place it noticed. This module produces three of them on purpose and prints the
name and the message, plus the correlation id that ties a log line to the request or task it belongs
to.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from xyberos import App, ConfigurationError, Inject, LifecycleStateError, Settings
from xyberos.errors import DependencyCycleError
from xyberos.runtime.context import bind_correlation_id, get_correlation_id


class First:
    """Depends on ``Second``, which depends on ``First``: a cycle, not a missing provider."""

    def __init__(self, other: Annotated[Second, Inject()]) -> None:
        self.other = other


class Second:
    """The other half of the cycle."""

    def __init__(self, other: Annotated[First, Inject()]) -> None:
        self.other = other


def report(label: str, error: BaseException) -> None:
    """Print an error the way a reader should learn to read one."""
    print(f"{label}: {type(error).__name__}: {error}")


async def main() -> None:
    """Trigger three failures and show the message each one gives."""
    try:
        await App().resolve(First)
    except LifecycleStateError as error:
        report("resolving before startup", error)

    try:
        Settings.load(environ={"XYBEROS_APP__UNKNOWN": "1"})
    except ConfigurationError as error:
        report("a misspelled setting", error)

    cycled = App()
    cycled.provide(First)
    cycled.provide(Second)
    try:
        cycled.validate()
    except DependencyCycleError as error:
        report("two services that need each other", error)

    with bind_correlation_id("lesson-14"):
        print("correlation id in this block:", get_correlation_id())


if __name__ == "__main__":
    asyncio.run(main())
