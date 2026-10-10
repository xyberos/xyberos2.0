"""Cancellation is cooperative and prompt before a step starts, and leaves no task behind."""

import asyncio

import pytest

from xyberos import (
    CancellationToken,
    Retry,
    StepContext,
    Workflow,
    WorkflowCancelledError,
    WorkflowExecutor,
    WorkflowTimeoutError,
)
from xyberos.execution import (
    Backoff,
    EventType,
    FakeExternalService,
    ManualClock,
    Reply,
    pending_tasks,
)


def test_cancelling_a_parent_token_cancels_its_children() -> None:
    parent = CancellationToken()
    child = parent.child()

    assert not child.cancelled

    parent.cancel("stop")

    assert parent.cancelled
    assert parent.reason == "stop"
    assert child.cancelled
    assert child.reason == "stop"


def test_a_child_of_a_cancelled_token_starts_cancelled() -> None:
    parent = CancellationToken()
    parent.cancel("too late")

    assert parent.child().cancelled


def test_cancelling_twice_keeps_the_first_reason() -> None:
    token = CancellationToken()

    token.cancel("first")
    token.cancel("second")

    assert token.reason == "first"


def test_waiting_on_a_cancelled_token_returns_immediately() -> None:
    async def scenario() -> None:
        token = CancellationToken()
        token.cancel("ready")

        await asyncio.wait_for(token.wait(), timeout=1.0)

    asyncio.run(scenario())


def test_step_context_check_reports_cancellation() -> None:
    token = CancellationToken()
    context = StepContext(
        workflow="demo",
        version="1",
        step="only",
        attempt=1,
        cancellation=token,
        clock=ManualClock(),
    )

    context.check()
    token.cancel("stop now")

    with pytest.raises(WorkflowCancelledError, match="stop now"):
        context.check()


def test_step_context_check_reports_an_expired_deadline() -> None:
    clock = ManualClock()
    context = StepContext(
        workflow="demo",
        version="1",
        step="only",
        attempt=1,
        cancellation=CancellationToken(),
        clock=clock,
        deadline=1.0,
    )

    assert context.remaining() == 1.0
    assert not context.expired()

    clock.advance(1.0)

    assert context.remaining() == 0.0
    assert context.expired()
    with pytest.raises(WorkflowTimeoutError, match="exceeded its deadline"):
        context.check()


def test_a_token_cancelled_before_the_run_prevents_every_step() -> None:
    async def scenario() -> None:
        ran: list[str] = []
        events: list[EventType] = []

        async def only(value: object, context: object) -> object:
            ran.append("only")
            return value

        def record(event: object) -> None:
            events.append(event.type)  # type: ignore[attr-defined]

        token = CancellationToken()
        token.cancel("stop before start")

        with pytest.raises(WorkflowCancelledError, match="before step 'only' could start"):
            await (
                Workflow("demo")
                .step("only", only)
                .run(
                    cancellation=token,
                    on_event=record,  # type: ignore[arg-type]
                )
            )

        assert ran == []
        assert events == [EventType.WORKFLOW_STARTED, EventType.WORKFLOW_CANCELLED]
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_cancellation_during_a_step_is_observed_by_a_cooperative_step() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        token = CancellationToken()
        observed: list[str] = []

        async def cooperative(value: object, context: object) -> object:
            try:
                await clock.sleep(10.0)
            except asyncio.CancelledError:
                observed.append("cancelled")
                raise
            return value

        workflow = Workflow("demo").step("only", cooperative)
        task = asyncio.ensure_future(
            workflow.run(cancellation=token, executor=WorkflowExecutor(clock=clock))
        )
        await clock.wait_for_sleepers(1)
        token.cancel("stop during")

        with pytest.raises(WorkflowCancelledError) as caught:
            await task

        assert caught.value.step == "only"
        assert observed == ["cancelled"]
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_cancellation_during_a_retry_pause_stops_retrying() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        token = CancellationToken()
        service = FakeExternalService([Reply.rate_limited()], clock=clock)

        async def fetch(value: object, context: object) -> object:
            return await service.call()

        workflow = Workflow("demo").step(
            "fetch", fetch, retry=Retry(max_attempts=5, backoff=Backoff(initial=1.0))
        )
        task = asyncio.ensure_future(
            workflow.run(cancellation=token, executor=WorkflowExecutor(clock=clock))
        )
        await clock.wait_for_sleepers(1)
        token.cancel("stop retrying")

        with pytest.raises(WorkflowCancelledError, match="while waiting to retry"):
            await task

        assert service.calls == 1
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_cancellation_takes_precedence_over_the_deadline() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        token = CancellationToken()

        async def hang(value: object, context: object) -> object:
            await asyncio.Future()
            return None

        workflow = Workflow("demo").step("hang", hang)
        task = asyncio.ensure_future(
            workflow.run(executor=WorkflowExecutor(clock=clock), cancellation=token, timeout=1.0)
        )
        await clock.wait_for_sleepers(1)

        token.cancel("cancelled first")
        clock.advance(1.0)

        with pytest.raises(WorkflowCancelledError, match="cancelled first"):
            await task

        assert pending_tasks() == []

    asyncio.run(scenario())


def test_a_step_can_stop_the_run_by_raising_a_cancellation_error() -> None:
    async def scenario() -> None:
        ran: list[str] = []

        async def first(value: object, context: object) -> object:
            ran.append("first")
            raise WorkflowCancelledError("the upstream service asked us to stop")

        async def second(value: object, context: object) -> object:
            ran.append("second")
            return value

        workflow = Workflow("demo").step("first", first).step("second", second)

        with pytest.raises(WorkflowCancelledError, match="asked us to stop"):
            await workflow.run()

        assert ran == ["first"]
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_cancellation_between_steps_stops_the_next_step() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        token = CancellationToken()
        ran: list[str] = []

        async def first(value: object, context: object) -> object:
            ran.append("first")
            token.cancel("stopping after the first step")
            return value

        async def second(value: object, context: object) -> object:
            ran.append("second")
            return value

        workflow = Workflow("demo").step("first", first).step("second", second)
        workflow = workflow.edge("first", "second")

        with pytest.raises(WorkflowCancelledError, match="before step 'second' could start"):
            await workflow.run(cancellation=token, executor=WorkflowExecutor(clock=clock))

        assert ran == ["first"]
        assert pending_tasks() == []

    asyncio.run(scenario())
