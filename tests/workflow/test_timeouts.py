"""Step timeouts are per attempt and the run deadline bounds everything."""

import asyncio

import pytest

from xyberos import (
    Backoff,
    Retry,
    RetryExhaustedError,
    StepContext,
    StepStatus,
    StepTimeoutError,
    Workflow,
    WorkflowExecutor,
    WorkflowTimeoutError,
)
from xyberos.execution import EventType, FakeExternalService, ManualClock, Reply, pending_tasks


def hanging_step():
    async def hang(value: object, context: object) -> object:
        await asyncio.Future()
        return value

    return hang


def test_a_step_timeout_raises_a_structured_error() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        workflow = Workflow("demo").step("hang", hanging_step(), timeout=1.0)
        task = asyncio.ensure_future(workflow.run(executor=WorkflowExecutor(clock=clock)))

        with pytest.raises(StepTimeoutError) as caught:
            await clock.drive(task)

        error = caught.value
        assert error.step == "hang"
        assert error.workflow == "demo"
        assert [attempt.status for attempt in error.attempts] == [StepStatus.TIMED_OUT]
        assert clock.sleeps == (1.0,)
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_a_step_timeout_is_not_retried_by_default() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        workflow = Workflow("demo").step(
            "hang", hanging_step(), timeout=1.0, retry=Retry(max_attempts=3, backoff=Backoff())
        )
        task = asyncio.ensure_future(workflow.run(executor=WorkflowExecutor(clock=clock)))

        with pytest.raises(StepTimeoutError) as caught:
            await clock.drive(task)

        assert len(caught.value.attempts) == 1
        assert clock.sleeps == (1.0,)

    asyncio.run(scenario())


def test_a_step_timeout_can_be_retried_when_the_policy_names_it() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        workflow = Workflow("demo").step(
            "hang",
            hanging_step(),
            timeout=1.0,
            retry=Retry(
                max_attempts=2, retry_on=(StepTimeoutError,), backoff=Backoff(initial=0.25)
            ),
        )
        task = asyncio.ensure_future(workflow.run(executor=WorkflowExecutor(clock=clock)))

        with pytest.raises(RetryExhaustedError) as caught:
            await clock.drive(task)

        assert [attempt.status for attempt in caught.value.attempts] == [
            StepStatus.TIMED_OUT,
            StepStatus.TIMED_OUT,
        ]
        assert clock.sleeps == (1.0, 0.25, 1.0)

    asyncio.run(scenario())


def test_a_step_timeout_is_smaller_than_the_run_budget() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        workflow = Workflow("demo").step("hang", hanging_step(), timeout=1.0)
        task = asyncio.ensure_future(
            workflow.run(executor=WorkflowExecutor(clock=clock), timeout=10.0)
        )

        with pytest.raises(StepTimeoutError):
            await clock.drive(task)

        assert clock.monotonic() == 1.0

    asyncio.run(scenario())


def test_the_run_deadline_stops_a_running_step() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        service = FakeExternalService([Reply.slow(30.0)], clock=clock)

        async def fetch(value: object, context: object) -> object:
            return await service.call()

        workflow = Workflow("demo").step("fetch", fetch)
        task = asyncio.ensure_future(
            workflow.run(executor=WorkflowExecutor(clock=clock), timeout=2.0)
        )
        await clock.wait_for_sleepers(2)  # the step's latency and the run's deadline
        clock.advance(2.0)

        with pytest.raises(WorkflowTimeoutError) as caught:
            await task

        assert caught.value.step == "fetch"
        assert service.observed_cancellations == 1
        assert clock.monotonic() == 2.0
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_the_run_deadline_is_enforced_before_the_next_step_starts() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        ran: list[str] = []

        async def overshoot(value: object, context: StepContext) -> object:
            context.clock.advance(5.0)  # type: ignore[attr-defined]
            return value

        async def afterwards(value: object, context: object) -> object:
            ran.append("afterwards")
            return value

        workflow = (
            Workflow("demo").step("overshoot", overshoot).step("afterwards", afterwards)
        ).edge("overshoot", "afterwards")

        with pytest.raises(WorkflowTimeoutError, match="before step 'afterwards' could start"):
            await workflow.run(executor=WorkflowExecutor(clock=clock), timeout=1.0)

        assert ran == []
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_a_run_deadline_is_reported_on_the_workflow_events() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        events: list[EventType] = []

        def record(event: object) -> None:
            events.append(event.type)  # type: ignore[attr-defined]

        workflow = Workflow("demo").step("hang", hanging_step())
        task = asyncio.ensure_future(
            workflow.run(
                executor=WorkflowExecutor(clock=clock),
                timeout=1.0,
                on_event=record,  # type: ignore[arg-type]
            )
        )

        with pytest.raises(WorkflowTimeoutError):
            await clock.drive(task)

        assert events == [
            EventType.WORKFLOW_STARTED,
            EventType.STEP_STARTED,
            EventType.STEP_TIMED_OUT,
            EventType.WORKFLOW_TIMED_OUT,
        ]

    asyncio.run(scenario())
