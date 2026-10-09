from __future__ import annotations

import asyncio
import inspect
import time
from concurrent.futures import Executor
from typing import Any, Mapping

from .contracts import (
    ExecutionPolicy,
    FlowDefinition,
    FlowResult,
    FlowState,
    FlowStep,
    StepTrace,
    TraceObserver,
)
from .errors import FlowExecutionError, FlowObserverError, FlowTimeoutError


class FlowEngine:
    """Sequential deterministic executor for typed flow steps."""

    def __init__(
        self,
        process_executor: Executor | None = None,
        *,
        dependencies: Mapping[str, Any] | None = None,
        max_concurrent_runs: int = 100,
        trace_observer: TraceObserver | None = None,
    ) -> None:
        if (
            not isinstance(max_concurrent_runs, int)
            or isinstance(max_concurrent_runs, bool)
            or max_concurrent_runs < 1
        ):
            raise ValueError("max_concurrent_runs must be a positive integer.")
        self._process_executor = process_executor
        self._dependencies = dict(dependencies or {})
        self._run_limit = asyncio.Semaphore(max_concurrent_runs)
        self._trace_observer = trace_observer

    async def run(self, flow: FlowDefinition, input_value: Any) -> FlowResult:
        started_at = time.monotonic()
        deadline = (
            started_at + flow.timeout_seconds
            if flow.timeout_seconds is not None
            else None
        )
        remaining = deadline - time.monotonic() if deadline is not None else None
        try:
            if remaining is None:
                await self._run_limit.acquire()
            elif remaining <= 0:
                raise asyncio.TimeoutError
            else:
                await asyncio.wait_for(self._run_limit.acquire(), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise FlowTimeoutError(flow.name) from exc

        try:
            return await self._execute(flow, input_value, deadline)
        finally:
            self._run_limit.release()

    async def _execute(
        self,
        flow: FlowDefinition,
        input_value: Any,
        deadline: float | None,
    ) -> FlowResult:
        state = FlowState(
            input=input_value,
            dependencies=dict(self._dependencies),
        )
        trace: list[StepTrace] = []

        for step in flow.steps:
            remaining = deadline - time.monotonic() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                raise FlowTimeoutError(flow.name, trace=tuple(trace))
            step_started = time.monotonic()
            if step.condition is not None:
                try:
                    should_run = step.condition(state)
                    if inspect.isawaitable(should_run):
                        if inspect.iscoroutine(should_run):
                            should_run.close()
                        raise TypeError("Flow step conditions must be synchronous.")
                    if not isinstance(should_run, bool):
                        raise TypeError("Flow step conditions must return bool.")
                except Exception as exc:
                    record = StepTrace(
                        step.name,
                        "failed",
                        0,
                        time.monotonic() - step_started,
                    )
                    trace.append(record)
                    await self._notify_observer(flow.name, record)
                    raise FlowExecutionError(
                        flow.name,
                        step.name,
                        0,
                        tuple(trace),
                    ) from exc
                if not should_run:
                    elapsed = time.monotonic() - step_started
                    if deadline is not None and time.monotonic() >= deadline:
                        record = StepTrace(step.name, "timed_out", 0, elapsed)
                        trace.append(record)
                        await self._notify_observer(flow.name, record)
                        raise FlowTimeoutError(flow.name, trace=tuple(trace))
                    record = StepTrace(step.name, "skipped", 0, elapsed)
                    trace.append(record)
                    await self._notify_observer(flow.name, record)
                    continue

            remaining = deadline - time.monotonic() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                record = StepTrace(
                    step.name,
                    "timed_out",
                    0,
                    time.monotonic() - step_started,
                )
                trace.append(record)
                await self._notify_observer(flow.name, record)
                raise FlowTimeoutError(flow.name, trace=tuple(trace))
            timeout = step.timeout_seconds
            flow_deadline_is_nearer = False
            if remaining is not None and (
                timeout is None or remaining <= timeout
            ):
                timeout = remaining
                flow_deadline_is_nearer = True

            try:
                result, attempts = await self._run_step(step, state, timeout)
            except _StepTimedOut as exc:
                record = StepTrace(
                    step.name,
                    "timed_out",
                    exc.attempts,
                    time.monotonic() - step_started,
                )
                trace.append(record)
                await self._notify_observer(flow.name, record)
                if flow_deadline_is_nearer:
                    raise FlowTimeoutError(
                        flow.name,
                        trace=tuple(trace),
                    ) from exc.__cause__
                raise FlowTimeoutError(
                    flow.name,
                    step.name,
                    tuple(trace),
                ) from exc.__cause__
            except _StepFailed as exc:
                record = StepTrace(
                    step.name,
                    "failed",
                    exc.attempts,
                    time.monotonic() - step_started,
                )
                trace.append(record)
                await self._notify_observer(flow.name, record)
                raise FlowExecutionError(
                    flow.name,
                    step.name,
                    exc.attempts,
                    tuple(trace),
                ) from exc.cause
            except _StepCancelled as exc:
                record = StepTrace(
                    step.name,
                    "cancelled",
                    exc.attempts,
                    time.monotonic() - step_started,
                )
                trace.append(record)
                await self._notify_observer(flow.name, record)
                raise exc.cancellation

            remaining = deadline - time.monotonic() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                record = StepTrace(
                    step.name,
                    "timed_out",
                    attempts,
                    time.monotonic() - step_started,
                )
                trace.append(record)
                await self._notify_observer(flow.name, record)
                raise FlowTimeoutError(flow.name, trace=tuple(trace))

            state.outputs[step.name] = result
            record = StepTrace(
                step.name,
                "succeeded",
                attempts,
                time.monotonic() - step_started,
            )
            trace.append(record)
            await self._notify_observer(flow.name, record)

        if deadline is not None and time.monotonic() >= deadline:
            raise FlowTimeoutError(flow.name, trace=tuple(trace))
        return FlowResult(flow.name, state, tuple(trace))

    async def _notify_observer(
        self,
        flow_name: str,
        record: StepTrace,
    ) -> None:
        if self._trace_observer is None:
            return
        try:
            result = self._trace_observer(record)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            raise FlowObserverError(flow_name, exc) from exc

    async def _run_step(
        self,
        step: FlowStep,
        state: FlowState,
        timeout: float | None,
    ) -> tuple[Any, int]:
        attempts = 0
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            attempts += 1
            try:
                remaining = deadline - time.monotonic() if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    raise _StepTimedOut(attempts - 1)
                operation = self._invoke(step, state)
                if remaining is None:
                    result = await operation
                else:
                    result = await asyncio.wait_for(
                        operation,
                        timeout=remaining,
                    )
                return result, attempts
            except asyncio.CancelledError as exc:
                raise _StepCancelled(attempts, exc) from exc
            except _StepTimedOut:
                raise
            except asyncio.TimeoutError:
                raise _StepTimedOut(attempts) from None
            except Exception as exc:
                if (
                    attempts >= step.retry.max_attempts
                    or not isinstance(exc, step.retry.retry_on)
                ):
                    raise _StepFailed(attempts, exc) from exc
                if step.retry.delay_seconds:
                    await asyncio.sleep(step.retry.delay_seconds)

    async def _invoke(self, step: FlowStep, state: FlowState) -> Any:
        if step.policy is ExecutionPolicy.ASYNC:
            is_async_callable = inspect.iscoroutinefunction(
                step.handler
            ) or inspect.iscoroutinefunction(getattr(step.handler, "__call__", None))
            if not is_async_callable:
                raise TypeError(
                    f"Async flow step '{step.name}' must use an async handler."
                )
            result = step.handler(state)
            if not inspect.isawaitable(result):
                raise TypeError(
                    f"Async flow step '{step.name}' must return an awaitable."
                )
            return await result

        if inspect.iscoroutinefunction(step.handler) or inspect.iscoroutinefunction(
            getattr(step.handler, "__call__", None)
        ):
            raise TypeError(
                f"Flow step '{step.name}' uses {step.policy.value} policy "
                "but its handler is async."
            )

        if step.policy is ExecutionPolicy.SYNC:
            result = step.handler(state)
        elif step.policy is ExecutionPolicy.THREAD:
            result = await asyncio.to_thread(step.handler, state)
        elif step.policy is ExecutionPolicy.PROCESS:
            if self._process_executor is None:
                raise RuntimeError(
                    f"Flow step '{step.name}' requires an injected process executor."
                )
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._process_executor,
                step.handler,
                state,
            )
        else:
            raise ValueError(f"Unsupported execution policy: {step.policy!r}")

        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError(
                f"Flow step '{step.name}' returned an awaitable under "
                f"{step.policy.value} policy."
            )
        return result

class _StepFailed(Exception):
    def __init__(self, attempts: int, cause: Exception) -> None:
        self.attempts = attempts
        self.cause = cause


class _StepTimedOut(Exception):
    def __init__(self, attempts: int) -> None:
        self.attempts = attempts


class _StepCancelled(Exception):
    def __init__(self, attempts: int, cancellation: asyncio.CancelledError) -> None:
        self.attempts = attempts
        self.cancellation = cancellation
