"""Retries are bounded, policy driven, and their timing is deterministic."""

import asyncio
from random import Random

import pytest

from xyberos import (
    Backoff,
    Retry,
    RetryExhaustedError,
    StepStatus,
    TransientError,
    Workflow,
    WorkflowExecutionError,
    WorkflowExecutor,
)
from xyberos.execution import (
    EventType,
    FakeExternalService,
    ManualClock,
    Reply,
    pending_tasks,
)


class UpstreamError(TransientError):
    """A caller-defined transient failure, retryable by default."""


def fetch_step(service: FakeExternalService):
    async def fetch(value: object, context: object) -> object:
        return await service.call(query=value)

    return fetch


def test_without_a_retry_policy_a_failure_is_reported_once() -> None:
    async def scenario() -> None:
        service = FakeExternalService([Reply.rate_limited()])
        workflow = Workflow("demo").step("fetch", fetch_step(service))

        with pytest.raises(WorkflowExecutionError) as caught:
            await workflow.run()

        error = caught.value
        assert type(error) is WorkflowExecutionError
        assert service.calls == 1
        assert [attempt.status for attempt in error.attempts] == [StepStatus.FAILED]
        assert error.attempts[0].error_type == "RateLimitError"

    asyncio.run(scenario())


def test_a_transient_failure_is_retried_until_it_succeeds() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        service = FakeExternalService(
            [Reply.rate_limited(), Reply.transient(), Reply.ok("done")], clock=clock
        )
        workflow = Workflow("demo").step(
            "fetch", fetch_step(service), retry=Retry(max_attempts=3, backoff=Backoff(initial=0.5))
        )
        task = asyncio.ensure_future(
            workflow.run(executor=WorkflowExecutor(clock=clock, random=Random(1)))
        )

        result = await clock.drive(task)

        assert result.value == "done"
        assert service.calls == 3
        assert result.outcome("fetch").attempt_count == 3
        assert clock.sleeps == (0.5, 1.0)
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_exhausted_retries_preserve_every_attempt() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        service = FakeExternalService([Reply.rate_limited()], clock=clock)
        workflow = Workflow("demo").step(
            "fetch", fetch_step(service), retry=Retry(max_attempts=3, backoff=Backoff(initial=1.0))
        )
        task = asyncio.ensure_future(workflow.run(executor=WorkflowExecutor(clock=clock)))

        with pytest.raises(RetryExhaustedError) as caught:
            await clock.drive(task)

        error = caught.value
        assert service.calls == 3
        assert [attempt.number for attempt in error.attempts] == [1, 2, 3]
        assert {attempt.status for attempt in error.attempts} == {StepStatus.FAILED}
        assert isinstance(error.__cause__, TransientError)
        assert clock.sleeps == (1.0, 2.0)
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_a_non_retryable_failure_is_not_retried() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def explode(value: object, context: object) -> object:
            calls.append("explode")
            raise ValueError("a programming error")

        workflow = Workflow("demo").step("explode", explode, retry=Retry(max_attempts=3))

        with pytest.raises(WorkflowExecutionError) as caught:
            await workflow.run()

        assert calls == ["explode"]
        assert len(caught.value.attempts) == 1
        assert caught.value.attempts[0].error_type == "ValueError"

    asyncio.run(scenario())


def test_the_policy_can_widen_the_retry_classification() -> None:
    async def scenario() -> None:
        calls: list[int] = []

        async def explode(value: object, context: object) -> object:
            calls.append(len(calls) + 1)
            raise ValueError("retried because the policy says so")

        workflow = Workflow("demo").step(
            "explode", explode, retry=Retry(max_attempts=2, retry_on=(ValueError,))
        )

        with pytest.raises(RetryExhaustedError) as caught:
            await workflow.run()

        assert calls == [1, 2]
        assert len(caught.value.attempts) == 2

    asyncio.run(scenario())


def test_the_policy_can_narrow_the_retry_classification() -> None:
    async def scenario() -> None:
        service = FakeExternalService([Reply.rate_limited()])
        workflow = Workflow("demo").step(
            "fetch", fetch_step(service), retry=Retry(max_attempts=3, retry_on=(KeyError,))
        )

        with pytest.raises(WorkflowExecutionError) as caught:
            await workflow.run()

        assert service.calls == 1
        assert len(caught.value.attempts) == 1

    asyncio.run(scenario())


def test_a_caller_defined_transient_error_is_retryable_by_default() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def flaky(value: object, context: object) -> object:
            calls.append("attempt")
            if len(calls) == 1:
                raise UpstreamError("the upstream service is unavailable")
            return "recovered"

        workflow = Workflow("demo").step("flaky", flaky, retry=Retry(max_attempts=2))

        result = await workflow.run()

        assert result.value == "recovered"
        assert calls == ["attempt", "attempt"]

    asyncio.run(scenario())


def test_a_retry_does_not_rerun_earlier_steps() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        calls: list[str] = []
        service = FakeExternalService([Reply.rate_limited(), Reply.ok("done")], clock=clock)

        async def first(value: object, context: object) -> object:
            calls.append("first")
            return value

        async def flaky(value: object, context: object) -> object:
            calls.append("flaky")
            return await service.call()

        workflow = (
            Workflow("demo")
            .step("first", first)
            .step("flaky", flaky, retry=Retry(max_attempts=2, backoff=Backoff(initial=0.5)))
            .edge("first", "flaky")
        )
        task = asyncio.ensure_future(workflow.run(executor=WorkflowExecutor(clock=clock)))

        result = await clock.drive(task)

        assert result.value == "done"
        assert calls == ["first", "flaky", "flaky"]
        assert result.outcome("first").attempt_count == 1

    asyncio.run(scenario())


def test_retry_events_are_emitted_in_order() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        service = FakeExternalService(
            [Reply.rate_limited(), Reply.rate_limited(), Reply.ok("done")], clock=clock
        )
        events: list[EventType] = []
        delays: list[str | None] = []

        def record(event: object) -> None:
            events.append(event.type)  # type: ignore[attr-defined]
            delays.append(event.detail)  # type: ignore[attr-defined]

        workflow = Workflow("demo").step(
            "fetch", fetch_step(service), retry=Retry(max_attempts=3, backoff=Backoff(initial=0.5))
        )
        task = asyncio.ensure_future(
            workflow.run(executor=WorkflowExecutor(clock=clock), on_event=record)  # type: ignore[arg-type]
        )

        await clock.drive(task)

        assert events == [
            EventType.WORKFLOW_STARTED,
            EventType.STEP_STARTED,
            EventType.STEP_FAILED,
            EventType.STEP_RETRIED,
            EventType.STEP_STARTED,
            EventType.STEP_FAILED,
            EventType.STEP_RETRIED,
            EventType.STEP_STARTED,
            EventType.STEP_SUCCEEDED,
            EventType.WORKFLOW_SUCCEEDED,
        ]
        assert delays[3] == "retrying in 0.5s"
        assert delays[6] == "retrying in 1s"

    asyncio.run(scenario())


def test_backoff_delays_are_exponential_and_capped() -> None:
    backoff = Backoff(initial=1.0, multiplier=3.0, max_delay=5.0)

    delays = [backoff.delay_for(attempt, random=Random(0)) for attempt in (1, 2, 3, 4)]

    assert delays == [1.0, 3.0, 5.0, 5.0]


def test_jitter_shortens_delays_within_the_declared_fraction() -> None:
    jittered = Backoff(initial=1.0, multiplier=1.0, max_delay=10.0, jitter=0.5)

    delays = [jittered.delay_for(1, random=Random(seed)) for seed in range(20)]

    assert all(0.5 <= delay <= 1.0 for delay in delays)
    assert len(set(delays)) > 1
    assert (
        Backoff(initial=1.0, multiplier=1.0, max_delay=10.0).delay_for(1, random=Random(1)) == 1.0
    )
