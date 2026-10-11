"""Events are sequenced, structured, and never carry payload."""

import asyncio

import pytest

from xyberos import (
    EventType,
    Workflow,
    WorkflowEvent,
    WorkflowExecutionError,
    WorkflowExecutor,
    bind_correlation_id,
)
from xyberos.execution import ManualClock


def test_a_successful_run_emits_a_sequenced_event_stream() -> None:
    async def scenario() -> None:
        events: list[WorkflowEvent] = []
        # A manual clock: a duration read from the system clock is quantised. Windows advances
        # time.monotonic in 15.6 ms steps, so an instantaneous step measures 0.0 there and a small
        # non-zero number on a Linux runner's clock. Injecting the clock makes the executor's
        # arithmetic the subject of the assertion rather than the host's timer.
        clock = ManualClock(start=100.0)

        async def only(value: object, context: object) -> object:
            return value

        await (
            Workflow("demo")
            .step("only", only)
            .run(input="x", on_event=events.append, executor=WorkflowExecutor(clock=clock))
        )

        assert [event.type for event in events] == [
            EventType.WORKFLOW_STARTED,
            EventType.STEP_STARTED,
            EventType.STEP_SUCCEEDED,
            EventType.WORKFLOW_SUCCEEDED,
        ]
        assert [event.sequence for event in events] == [1, 2, 3, 4]
        assert {event.workflow for event in events} == {"demo"}
        assert {event.version for event in events} == {"1"}
        assert events[1].step == "only"
        assert events[1].attempt == 1
        assert events[2].duration == 0.0

    asyncio.run(scenario())


def test_events_never_carry_input_output_or_error_messages() -> None:
    async def scenario() -> None:
        events: list[WorkflowEvent] = []

        async def only(value: object, context: object) -> object:
            assert value == "secret-input"
            raise ValueError("secret-error-message")

        workflow = Workflow("demo").step("only", only)

        with pytest.raises(WorkflowExecutionError):
            await workflow.run(input="secret-input", on_event=events.append)

        rendered = "\n".join(event.render() for event in events)

        assert "secret-input" not in rendered
        assert "secret-error-message" not in rendered
        assert "ValueError" in rendered
        assert [event.type for event in events][-2:] == [
            EventType.STEP_FAILED,
            EventType.WORKFLOW_FAILED,
        ]

    asyncio.run(scenario())


def test_events_carry_the_correlation_id_of_the_caller() -> None:
    async def scenario() -> None:
        events: list[WorkflowEvent] = []

        async def only(value: object, context: object) -> object:
            return value

        with bind_correlation_id("corr-events"):
            await Workflow("demo").step("only", only).run(on_event=events.append)

        assert {event.correlation_id for event in events} == {"corr-events"}

        events.clear()
        await Workflow("demo").step("only", only).run(on_event=events.append)

        assert {event.correlation_id for event in events} == {None}

    asyncio.run(scenario())


def test_event_timestamps_come_from_the_executor_clock() -> None:
    async def scenario() -> None:
        clock = ManualClock(start=100.0)
        events: list[WorkflowEvent] = []

        async def only(value: object, context: object) -> object:
            return value

        await (
            Workflow("demo")
            .step("only", only)
            .run(executor=WorkflowExecutor(clock=clock), on_event=events.append)
        )

        assert [event.timestamp for event in events] == [100.0, 100.0, 100.0, 100.0]

    asyncio.run(scenario())


def test_event_render_is_a_single_informative_line() -> None:
    event = WorkflowEvent(
        type=EventType.STEP_RETRIED,
        sequence=3,
        workflow="demo",
        version="1",
        timestamp=0.0,
        step="fetch",
        attempt=1,
        duration=0.5,
        detail="retrying in 1s",
        error_type="RateLimitError",
    )

    assert event.render() == (
        "#3 step_retried workflow=demo step=fetch attempt=1 duration=0.500000 "
        "error=RateLimitError retrying in 1s"
    )


def test_skipped_and_cancelled_steps_are_reported() -> None:
    async def scenario() -> None:
        events: list[WorkflowEvent] = []

        async def classify(value: object, context: object) -> object:
            return value

        async def never(value: object, context: object) -> object:
            return "never"

        workflow = (
            Workflow("demo")
            .step("classify", classify)
            .step("never", never)
            .edge("classify", "never", when=lambda value: False)
        )

        await workflow.run(input=None, on_event=events.append)

        assert [event.type for event in events] == [
            EventType.WORKFLOW_STARTED,
            EventType.STEP_STARTED,
            EventType.STEP_SUCCEEDED,
            EventType.STEP_SKIPPED,
            EventType.WORKFLOW_SUCCEEDED,
        ]
        assert events[3].detail == "no branch reached this step"

    asyncio.run(scenario())


def test_an_execution_without_a_sink_produces_no_events() -> None:
    async def scenario() -> None:
        async def only(value: object, context: object) -> object:
            return value

        result = await Workflow("demo").step("only", only).run(input="quiet")

        assert result.value == "quiet"

    asyncio.run(scenario())
