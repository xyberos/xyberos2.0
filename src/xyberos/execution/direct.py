"""Direct calls: one await, with the framework's deadline and cancellation guarantees.

A direct call sits below a workflow. Reach for it when a single function is the whole task, so the
three execution modes stay explicit in code and documentation: direct calls, workflow execution,
and the experimental durable executor in ``xyberos.durable``.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, TypeVar, cast

from xyberos.execution.executor import WorkflowExecutor
from xyberos.execution.policies import CancellationToken

T = TypeVar("T")


async def direct(
    func: Callable[..., Coroutine[Any, Any, T]],
    /,
    *args: object,
    timeout: float | None = None,
    cancellation: CancellationToken | None = None,
    name: str | None = None,
    executor: WorkflowExecutor | None = None,
    **kwargs: object,
) -> T:
    """Await one async callable under an optional deadline and cancellation token.

    The callable's own exception propagates unchanged and nothing is retried: a direct call is a
    plain await with cooperative stopping. Use a workflow when you need retries, branching, or
    per-step inspection.

    .. code-block:: python

        profile = await direct(load_profile, user_id, timeout=seconds(5))

    ``timeout`` is in seconds, ``name`` overrides the function name reported in errors, and
    ``executor`` supplies the clock and random source, which is how tests stay deterministic.
    """
    active = executor if executor is not None else WorkflowExecutor()
    return cast(
        T,
        await active.call(
            func,
            *args,
            timeout=timeout,
            cancellation=cancellation,
            name=name,
            **kwargs,
        ),
    )
