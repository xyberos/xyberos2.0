"""Walkthrough — the diagnostic context, and where it is carried rather than lost.

Run it with:

    python -m learn_production.observability02_context
"""

from __future__ import annotations

import asyncio
import threading
import time

from xyberos.runtime.context import (
    bind_context,
    bind_correlation_id,
    bind_deadline,
    capture_context_runner,
    create_task_in_context,
    get_context,
    get_deadline,
)


def observe(label: str) -> None:
    """Report the context this caller can see, from wherever it is called."""
    print(f"{label}:", get_context())


async def observe_async(label: str) -> None:
    """Report the context from inside a task."""
    observe(label)


async def main() -> None:
    """Bind a request context, then send work across each boundary and report what arrived."""
    print("before anything is bound:", get_context())

    with bind_correlation_id("req-7"), bind_context(tenant="acme"):
        observe("inside the request")

        # Tasks and `to_thread` carry the context already: both copy it. The helpers exist for the
        # boundaries that do not, not for these.
        await asyncio.create_task(observe_async("a task"))  # noqa: RUF006
        await create_task_in_context(observe_async("create_task_in_context"))
        await asyncio.to_thread(observe, "asyncio.to_thread")

        # A bare executor call does not: the executor's threads start from an empty context. This is
        # the boundary a blocking library call or a background worker is usually written with.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, observe, "run_in_executor, uncarried")
        runner = capture_context_runner(observe, "capture_context_runner, in that executor")
        await loop.run_in_executor(None, runner)

        # A thread started by hand is the same boundary, and the helper crosses it the same way.
        borrowed: list[dict[str, object]] = []
        plain = threading.Thread(target=lambda: borrowed.append(get_context()))
        carried = threading.Thread(target=capture_context_runner(borrowed.append, get_context()))
        for thread in (plain, carried):
            thread.start()
            thread.join()
        print("hand-started threads saw:", borrowed)

        with bind_deadline(time.monotonic() + 30):
            print("a deadline is bound:", get_deadline() is not None)
        print("and the deadline afterwards:", get_deadline())

    print("after the block:", get_context())


if __name__ == "__main__":
    asyncio.run(main())
