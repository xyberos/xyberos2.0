"""The workflow executor: structured concurrency over a validated definition.

The executor owns every task it creates and always awaits or cancels each one before returning, so
no execution outlives the call. Deadlines are absolute monotonic instants derived from the clock,
and cancellation is cooperative: the executor signals, and the step decides how to react within
its next await.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from logging import getLogger
from random import Random
from types import MappingProxyType
from typing import Any

from xyberos.errors import (
    RetryExhaustedError,
    StepTimeoutError,
    WorkflowCancelledError,
    WorkflowExecutionError,
    WorkflowTimeoutError,
    WorkflowValidationError,
)
from xyberos.execution.events import EventSink, EventType, WorkflowEvent
from xyberos.execution.models import (
    DIRECT_WORKFLOW,
    Attempt,
    Edge,
    Step,
    StepOutcome,
    StepStatus,
    Workflow,
    WorkflowResult,
)
from xyberos.execution.policies import CancellationToken, Clock, StepContext, SystemClock
from xyberos.runtime.context import (
    bind_context,
    bind_deadline,
    create_task_in_context,
    get_correlation_id,
)

_ABORT_ERRORS: dict[str, type[WorkflowExecutionError]] = {
    "failed": WorkflowExecutionError,
    "retry_exhausted": RetryExhaustedError,
    "step_timeout": StepTimeoutError,
    "timed_out": WorkflowTimeoutError,
    "cancelled": WorkflowCancelledError,
}

_ABORT_EVENTS: dict[str, EventType] = {
    "failed": EventType.WORKFLOW_FAILED,
    "retry_exhausted": EventType.WORKFLOW_FAILED,
    "step_timeout": EventType.WORKFLOW_FAILED,
    "timed_out": EventType.WORKFLOW_TIMED_OUT,
    "cancelled": EventType.WORKFLOW_CANCELLED,
}


class _Abort(Exception):
    """Internal control flow: the run stopped, and the public error follows once outcomes exist."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        step: str | None = None,
        attempts: tuple[Attempt, ...] = (),
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.step = step
        self.attempts = attempts
        self.cause = cause


@dataclass(frozen=True)
class _AttemptResult:
    """What a raced call produced: a value, an error, or the reason it was stopped."""

    output: object = None
    error: BaseException | None = None
    stop: str | None = None


class _EventLog:
    """Emits sequenced events for one run, and does nothing at all without a sink."""

    def __init__(
        self,
        sink: EventSink | None,
        *,
        workflow: str,
        version: str,
        correlation_id: str | None,
        clock: Clock,
    ) -> None:
        self._sink = sink
        self._workflow = workflow
        self._version = version
        self._correlation_id = correlation_id
        self._clock = clock
        self._sequence = 0

    def emit(
        self,
        event_type: EventType,
        *,
        step: str | None = None,
        attempt: int | None = None,
        duration: float | None = None,
        detail: str | None = None,
        error_type: str | None = None,
    ) -> None:
        if self._sink is None:
            return
        self._sequence += 1
        self._sink(
            WorkflowEvent(
                type=event_type,
                sequence=self._sequence,
                workflow=self._workflow,
                version=self._version,
                timestamp=self._clock.monotonic(),
                step=step,
                attempt=attempt,
                duration=duration,
                correlation_id=self._correlation_id,
                detail=detail,
                error_type=error_type,
            )
        )


def _type_name(value: object) -> str:
    if isinstance(value, tuple):
        return " | ".join(getattr(item, "__name__", repr(item)) for item in value)
    return getattr(value, "__name__", repr(value))


class WorkflowExecutor:
    """Runs validated workflows and single calls with deadlines, retries, and cancellation.

    Inject a clock, and a seeded random source for jitter, to make timing and retry behavior
    deterministic in tests.
    """

    def __init__(self, *, clock: Clock | None = None, random: Random | None = None) -> None:
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._random = random if random is not None else Random()

    @property
    def clock(self) -> Clock:
        """The clock this executor measures deadlines and backoff with."""
        return self._clock

    async def run(
        self,
        workflow: Workflow,
        *,
        input: object = None,
        timeout: float | None = None,
        cancellation: CancellationToken | None = None,
        on_event: EventSink | None = None,
    ) -> WorkflowResult:
        """Execute ``workflow`` and return its result.

        ``timeout`` is the budget for the whole run in seconds. A definition is validated before
        anything runs and the declared input type is checked before the first event is emitted, so a
        rejected call has no side effects.
        """
        workflow.validate()
        _require_positive(timeout, "timeout")
        _require_input(workflow, input)
        started = self._clock.monotonic()
        deadline = None if timeout is None else started + timeout
        token = cancellation if cancellation is not None else CancellationToken()
        events = _EventLog(
            on_event,
            workflow=workflow.name,
            version=workflow.version,
            correlation_id=get_correlation_id(),
            clock=self._clock,
        )
        outcomes: dict[str, StepOutcome] = {}
        outputs: dict[str, object] = {}
        produced: dict[str, object] = {}
        taken: set[tuple[str, str]] = set()
        waiters = {step.id: len(workflow.incoming(step.id)) for step in workflow.steps}
        ready = deque(step for step in workflow.steps if waiters[step.id] == 0)
        events.emit(EventType.WORKFLOW_STARTED, detail=f"steps={len(workflow.steps)}")
        try:
            while ready:
                step = ready.popleft()
                incoming = workflow.incoming(step.id)
                reached = [edge for edge in incoming if (edge.source, edge.target) in taken]
                if len(reached) > 1:
                    sources = ", ".join(sorted(edge.source for edge in reached))
                    raise _Abort(
                        "failed",
                        f"step {step.id!r} was reached by more than one branch ({sources}); "
                        "branches that merge into one step must be mutually exclusive",
                        step=step.id,
                    )
                if incoming and not reached:
                    outcomes[step.id] = StepOutcome(step=step.id, status=StepStatus.SKIPPED)
                    events.emit(
                        EventType.STEP_SKIPPED, step=step.id, detail="no branch reached this step"
                    )
                else:
                    _require_live(token, deadline, self._clock, workflow=workflow, step=step.id)
                    value = input if not incoming else produced[reached[0].source]
                    outcome = await self._execute_step(
                        workflow,
                        step,
                        value,
                        token=token,
                        deadline=deadline,
                        events=events,
                    )
                    outcomes[step.id] = outcome
                    produced[step.id] = outcome.output
                    outgoing = workflow.outgoing(step.id)
                    if outgoing:
                        selected = _select_edge(outgoing, outcome.output)
                        if selected is not None:
                            taken.add((selected.source, selected.target))
                    else:
                        outputs[step.id] = outcome.output
                for edge in workflow.outgoing(step.id):
                    waiters[edge.target] -= 1
                    if waiters[edge.target] == 0:
                        ready.append(workflow.step_by_id(edge.target))
        except _Abort as abort:
            events.emit(
                _ABORT_EVENTS[abort.kind],
                step=abort.step,
                detail=abort.message,
                error_type=_error_name(abort),
            )
            raise _ABORT_ERRORS[abort.kind](
                abort.message,
                workflow=workflow.name,
                step=abort.step,
                attempts=abort.attempts,
                outcomes=outcomes,
            ) from abort.cause
        duration = self._clock.monotonic() - started
        events.emit(
            EventType.WORKFLOW_SUCCEEDED, duration=duration, detail=f"outputs={len(outputs)}"
        )
        return WorkflowResult(
            workflow=workflow.name,
            version=workflow.version,
            outputs=MappingProxyType(outputs),
            steps=MappingProxyType(outcomes),
            duration=duration,
        )

    async def call(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        /,
        *args: object,
        timeout: float | None = None,
        cancellation: CancellationToken | None = None,
        name: str | None = None,
        **kwargs: object,
    ) -> object:
        """Run one callable under a deadline and a cancellation token, without wrapping it.

        A direct call is the boundary below a workflow: it does not retry, and the callable's own
        exception propagates unchanged. Only the framework's deadline and cancellation errors are
        added.
        """
        _require_positive(timeout, "timeout")
        deadline = None if timeout is None else self._clock.monotonic() + timeout
        token = cancellation if cancellation is not None else CancellationToken()
        label = name or getattr(func, "__name__", "call")
        if token.cancelled:
            raise WorkflowCancelledError(
                f"direct call {label!r} was cancelled before it started",
                workflow=DIRECT_WORKFLOW,
                step=label,
            )
        budget = None if deadline is None else max(deadline - self._clock.monotonic(), 0.0)
        with bind_context(workflow=DIRECT_WORKFLOW, workflow_step=label), bind_deadline(deadline):
            result = await self._race(
                func(*args, **kwargs),
                name=f"xyberos:direct:{label}",
                budget=budget,
                token=token,
                deadline=deadline,
            )
        if result.stop == "cancelled":
            raise WorkflowCancelledError(
                f"direct call {label!r} was cancelled", workflow=DIRECT_WORKFLOW, step=label
            )
        if result.stop is not None:
            raise WorkflowTimeoutError(
                f"direct call {label!r} exceeded its timeout of {timeout:g}s",
                workflow=DIRECT_WORKFLOW,
                step=label,
            )
        if result.error is not None:
            raise result.error
        return result.output

    async def _execute_step(
        self,
        workflow: Workflow,
        step: Step,
        value: object,
        *,
        token: CancellationToken,
        deadline: float | None,
        events: _EventLog,
    ) -> StepOutcome:
        retry = step.retry
        max_attempts = retry.max_attempts if retry is not None else 1
        started = self._clock.monotonic()
        attempts: list[Attempt] = []
        base = StepContext(
            workflow=workflow.name,
            version=workflow.version,
            step=step.id,
            attempt=1,
            cancellation=token,
            clock=self._clock,
            deadline=deadline,
            correlation_id=get_correlation_id(),
            logger=getLogger(f"xyberos.workflow.{workflow.name}"),
        )
        for number in range(1, max_attempts + 1):
            context = replace(base, attempt=number, cancellation=token.child())
            events.emit(EventType.STEP_STARTED, step=step.id, attempt=number)
            attempt_started = self._clock.monotonic()
            with (
                bind_context(
                    workflow=workflow.name, workflow_step=step.id, workflow_attempt=number
                ),
                bind_deadline(deadline),
            ):
                result = await self._race(
                    step.run(value, context),
                    name=f"xyberos:{workflow.name}:{step.id}",
                    budget=_attempt_budget(step, deadline, self._clock),
                    token=context.cancellation,
                    deadline=deadline,
                )
            context.cancellation.cancel("the attempt finished")
            duration = self._clock.monotonic() - attempt_started
            if result.stop == "cancelled":
                events.emit(
                    EventType.STEP_CANCELLED, step=step.id, attempt=number, duration=duration
                )
                raise _Abort(
                    "cancelled",
                    f"workflow {workflow.name!r} was cancelled during step {step.id!r} "
                    f"({token.reason or 'cancellation was requested'})",
                    step=step.id,
                    attempts=tuple(attempts),
                )
            if result.stop == "timed_out":
                attempts.append(
                    Attempt(number=number, status=StepStatus.TIMED_OUT, duration=duration)
                )
                events.emit(
                    EventType.STEP_TIMED_OUT,
                    step=step.id,
                    attempt=number,
                    duration=duration,
                    detail="the workflow deadline was reached",
                )
                raise _Abort(
                    "timed_out",
                    f"workflow {workflow.name!r} exceeded its deadline during step {step.id!r}",
                    step=step.id,
                    attempts=tuple(attempts),
                )
            error = result.error
            if result.stop == "step_timeout":
                error = StepTimeoutError(
                    f"step {step.id!r} exceeded its timeout of {step.timeout:g}s",
                    workflow=workflow.name,
                    step=step.id,
                    attempts=tuple(attempts),
                )
                attempts.append(
                    Attempt(number=number, status=StepStatus.TIMED_OUT, duration=duration)
                )
                events.emit(
                    EventType.STEP_TIMED_OUT,
                    step=step.id,
                    attempt=number,
                    duration=duration,
                    error_type=StepTimeoutError.__name__,
                )
            if error is None:
                attempts.append(
                    Attempt(number=number, status=StepStatus.SUCCEEDED, duration=duration)
                )
                events.emit(
                    EventType.STEP_SUCCEEDED, step=step.id, attempt=number, duration=duration
                )
                return StepOutcome(
                    step=step.id,
                    status=StepStatus.SUCCEEDED,
                    attempts=tuple(attempts),
                    output=result.output,
                    duration=self._clock.monotonic() - started,
                )
            if isinstance(error, WorkflowCancelledError):
                events.emit(
                    EventType.STEP_CANCELLED,
                    step=step.id,
                    attempt=number,
                    duration=duration,
                    error_type=type(error).__name__,
                )
                raise _Abort(
                    "cancelled",
                    f"workflow {workflow.name!r} was cancelled during step {step.id!r}: {error}",
                    step=step.id,
                    attempts=tuple(attempts),
                    cause=error,
                )
            if isinstance(error, WorkflowTimeoutError):
                attempts.append(
                    Attempt(
                        number=number,
                        status=StepStatus.TIMED_OUT,
                        duration=duration,
                        error_type=type(error).__name__,
                    )
                )
                events.emit(
                    EventType.STEP_TIMED_OUT,
                    step=step.id,
                    attempt=number,
                    duration=duration,
                    error_type=type(error).__name__,
                )
                raise _Abort(
                    "timed_out",
                    f"workflow {workflow.name!r} exceeded its deadline during step {step.id!r}: "
                    f"{error}",
                    step=step.id,
                    attempts=tuple(attempts),
                    cause=error,
                )
            if result.stop is None:
                attempts.append(
                    Attempt(
                        number=number,
                        status=StepStatus.FAILED,
                        duration=duration,
                        error_type=type(error).__name__,
                    )
                )
                events.emit(
                    EventType.STEP_FAILED,
                    step=step.id,
                    attempt=number,
                    duration=duration,
                    error_type=type(error).__name__,
                )
            retryable = retry is not None and retry.allows(error)
            if retryable and retry is not None and number < max_attempts:
                delay = retry.backoff.delay_for(number, random=self._random)
                events.emit(
                    EventType.STEP_RETRIED,
                    step=step.id,
                    attempt=number,
                    detail=f"retrying in {delay:g}s",
                )
                await self._pause(
                    delay,
                    token,
                    deadline,
                    workflow=workflow,
                    step=step.id,
                    attempts=tuple(attempts),
                )
                continue
            if retryable:
                kind = "retry_exhausted"
            elif isinstance(error, StepTimeoutError):
                kind = "step_timeout"
            else:
                kind = "failed"
            raise _Abort(
                kind,
                f"step {step.id!r} failed after {len(attempts)} attempt(s) with "
                f"{type(error).__name__}",
                step=step.id,
                attempts=tuple(attempts),
                cause=error,
            )
        raise AssertionError("unreachable: the retry loop always returns or raises")

    async def _pause(
        self,
        delay: float,
        token: CancellationToken,
        deadline: float | None,
        *,
        workflow: Workflow,
        step: str,
        attempts: tuple[Attempt, ...],
    ) -> None:
        """Wait out a backoff delay, stopping early if the run is cancelled or out of time."""
        budget = delay
        if deadline is not None:
            budget = min(delay, max(deadline - self._clock.monotonic(), 0.0))
        await self._race(
            self._clock.sleep(max(budget, 0.0)),
            name=f"xyberos:{workflow.name}:{step}:backoff",
            budget=None,
            token=token,
            deadline=None,
        )
        if token.cancelled:
            raise _Abort(
                "cancelled",
                f"workflow {workflow.name!r} was cancelled while waiting to retry step {step!r}",
                step=step,
                attempts=attempts,
            )
        if deadline is not None and self._clock.monotonic() >= deadline:
            raise _Abort(
                "timed_out",
                f"workflow {workflow.name!r} exceeded its deadline while waiting to retry "
                f"step {step!r}",
                step=step,
                attempts=attempts,
            )

    async def _race(
        self,
        call: Coroutine[Any, Any, Any],
        *,
        name: str,
        budget: float | None,
        token: CancellationToken,
        deadline: float | None,
    ) -> _AttemptResult:
        """Run ``call`` against its stop conditions, leaving no task behind on either path."""
        task = create_task_in_context(call, name=name)
        watch = create_task_in_context(self._watch(budget, token), name=f"{name}:stop")
        try:
            await asyncio.wait({task, watch}, return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                if task.cancelled():
                    return _AttemptResult(stop="cancelled")
                error = task.exception()
                if error is None:
                    return _AttemptResult(output=task.result())
                return _AttemptResult(error=error)
            return _AttemptResult(stop=self._stop_reason(token, deadline))
        finally:
            for pending in (task, watch):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, watch, return_exceptions=True)

    async def _watch(self, budget: float | None, token: CancellationToken) -> None:
        """Return once the attempt must stop: its budget elapsed, or cancellation was asked for."""
        stoppers: list[asyncio.Task[None]] = [
            create_task_in_context(token.wait(), name="xyberos:run:cancellation")
        ]
        if budget is not None:
            stoppers.append(
                create_task_in_context(
                    self._clock.sleep(max(budget, 0.0)), name="xyberos:run:budget"
                )
            )
        try:
            await asyncio.wait(stoppers, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for pending in stoppers:
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(*stoppers, return_exceptions=True)

    def _stop_reason(self, token: CancellationToken, deadline: float | None) -> str:
        """Decide why an attempt stopped, with cancellation taking precedence over the deadline."""
        if token.cancelled:
            return "cancelled"
        if deadline is not None and self._clock.monotonic() >= deadline:
            return "timed_out"
        return "step_timeout"


def _error_name(abort: _Abort) -> str:
    if abort.cause is not None:
        return type(abort.cause).__name__
    return _ABORT_ERRORS[abort.kind].__name__


def _require_positive(value: float | None, label: str) -> None:
    if value is not None and value <= 0:
        raise WorkflowValidationError(f"{label} must be greater than zero, got {value!r}")


def _require_input(workflow: Workflow, value: object) -> None:
    declared = workflow.input_type
    if declared is None or isinstance(value, declared):
        return
    raise WorkflowExecutionError(
        f"workflow {workflow.name!r} expects input of type {_type_name(declared)}, "
        f"got {type(value).__name__}",
        workflow=workflow.name,
    )


def _require_live(
    token: CancellationToken,
    deadline: float | None,
    clock: Clock,
    *,
    workflow: Workflow,
    step: str,
) -> None:
    """Refuse to start a step when the run is already cancelled or out of time."""
    if token.cancelled:
        raise _Abort(
            "cancelled",
            f"workflow {workflow.name!r} was cancelled before step {step!r} could start "
            f"({token.reason or 'cancellation was requested'})",
            step=step,
        )
    if deadline is not None and clock.monotonic() >= deadline:
        raise _Abort(
            "timed_out",
            f"workflow {workflow.name!r} exceeded its deadline before step {step!r} could start",
            step=step,
        )


def _attempt_budget(step: Step, deadline: float | None, clock: Clock) -> float | None:
    """How long one attempt may take: its own timeout, the remaining budget, or the smaller one."""
    budget = step.timeout
    if deadline is None:
        return budget
    remaining = max(deadline - clock.monotonic(), 0.0)
    return remaining if budget is None else min(budget, remaining)


def _select_edge(outgoing: tuple[Edge, ...], output: object) -> Edge | None:
    """Return the single edge a step's output selects.

    Conditional edges are considered in declaration order and the unconditional fallback is
    validated to come last, so at most one branch ever runs. ``None`` means no branch matched and
    the downstream steps are skipped.
    """
    for edge in outgoing:
        if edge.when is None:
            return edge
        if edge.when(output):
            return edge
    return None
