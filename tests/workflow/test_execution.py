"""Execution order, data flow, branching, tracing, and structured concurrency."""

import asyncio

import pytest

from xyberos import (
    StepContext,
    StepStatus,
    Workflow,
    WorkflowError,
    WorkflowExecutionError,
    WorkflowValidationError,
    bind_correlation_id,
    get_context,
    get_deadline,
)
from xyberos.execution import ManualClock, WorkflowExecutor, pending_tasks


def test_a_linear_workflow_runs_each_step_once_in_order() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def first(value: object, context: object) -> object:
            calls.append(f"first:{value}")
            return [value]

        async def second(value: object, context: object) -> object:
            calls.append(f"second:{value}")
            return value

        workflow = (
            Workflow("demo").step("first", first).step("second", second).edge("first", "second")
        )

        result = await workflow.run(input="seed")

        assert calls == ["first:seed", "second:['seed']"]
        assert result.workflow == "demo"
        assert result.version == "1"
        assert result.value == ["seed"]
        assert result.outcome("first").status is StepStatus.SUCCEEDED
        assert result.outcome("first").attempt_count == 1
        assert result.outcome("first").output == ["seed"]
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_a_single_step_workflow_is_its_own_entry_and_exit() -> None:
    async def scenario() -> None:
        async def only(value: object, context: object) -> object:
            return f"seen:{value}"

        result = await Workflow("demo").step("only", only).run(input="x")

        assert result.value == "seen:x"
        assert result.workflow == "demo"

    asyncio.run(scenario())


def test_a_step_receives_an_explicit_context() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        seen: list[tuple[object, ...]] = []

        async def inspect(value: object, context: StepContext) -> object:
            seen.append(
                (
                    context.workflow,
                    context.version,
                    context.step,
                    context.attempt,
                    context.logger.name,
                    context.clock is clock,
                    context.correlation_id,
                    context.remaining(),
                )
            )
            return value

        workflow = Workflow("demo", version="3").step("only", inspect)

        with bind_correlation_id("corr-1"):
            await workflow.run(input=1, executor=WorkflowExecutor(clock=clock))

        assert seen == [("demo", "3", "only", 1, "xyberos.workflow.demo", True, "corr-1", None)]

    asyncio.run(scenario())


def test_execution_binds_tracing_metadata_for_steps() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        observed: dict[str, object] = {}

        async def inspect(value: object, context: object) -> object:
            observed.update(get_context())
            observed["deadline"] = get_deadline()
            return value

        await (
            Workflow("demo", version="4")
            .step("only", inspect)
            .run(executor=WorkflowExecutor(clock=clock), timeout=5.0)
        )

        assert observed["workflow"] == "demo"
        assert observed["workflow_step"] == "only"
        assert observed["workflow_attempt"] == 1
        assert observed["deadline"] == 5.0

    asyncio.run(scenario())


def test_a_branch_runs_only_the_selected_edge() -> None:
    async def scenario() -> None:
        ran: list[str] = []

        async def classify(value: object, context: object) -> object:
            ran.append("classify")
            return value

        async def billing(value: object, context: object) -> str:
            ran.append("billing")
            return f"billing:{value}"

        async def general(value: object, context: object) -> str:
            ran.append("general")
            return f"general:{value}"

        async def report(value: object, context: object) -> str:
            ran.append("report")
            return f"report:{value}"

        workflow = (
            Workflow("demo")
            .step("classify", classify)
            .step("billing", billing)
            .step("general", general)
            .step("report", report)
            .edge("classify", "billing", when=lambda value: value == "billing")
            .edge("classify", "general")
            .edge("billing", "report")
            .edge("general", "report")
        )

        chosen = await workflow.run(input="billing")

        assert chosen.value == "report:billing:billing"
        assert ran == ["classify", "billing", "report"]
        assert chosen.outcome("general").status is StepStatus.SKIPPED

        ran.clear()
        other = await workflow.run(input="other")

        assert other.value == "report:general:other"
        assert ran == ["classify", "general", "report"]
        assert other.outcome("billing").status is StepStatus.SKIPPED

    asyncio.run(scenario())


def test_steps_without_a_matching_branch_are_skipped() -> None:
    async def scenario() -> None:
        ran: list[str] = []

        async def classify(value: object, context: object) -> object:
            return value

        async def billing(value: object, context: object) -> str:
            ran.append("billing")
            return "billing"

        workflow = (
            Workflow("demo")
            .step("classify", classify)
            .step("billing", billing)
            .edge("classify", "billing", when=lambda value: value == "billing")
        )

        result = await workflow.run(input="other")

        assert ran == []
        assert dict(result.outputs) == {}
        assert result.outcome("billing").status is StepStatus.SKIPPED
        with pytest.raises(WorkflowError, match="produced 0 outputs"):
            _ = result.value

    asyncio.run(scenario())


def test_a_branch_with_one_running_exit_still_yields_a_single_value() -> None:
    async def scenario() -> None:
        async def classify(value: object, context: object) -> object:
            return value

        async def billing(value: object, context: object) -> str:
            return "billing"

        async def general(value: object, context: object) -> str:
            return "general"

        workflow = (
            Workflow("demo")
            .step("classify", classify)
            .step("billing", billing)
            .step("general", general)
            .edge("classify", "billing", when=lambda value: value == "billing")
            .edge("classify", "general")
        )

        result = await workflow.run(input="billing")

        assert dict(result.outputs) == {"billing": "billing"}
        assert result.value == "billing"

    asyncio.run(scenario())


def test_a_workflow_with_two_exits_reports_two_outputs() -> None:
    async def scenario() -> None:
        async def start(value: object, context: object) -> str:
            return f"started:{value}"

        workflow = Workflow("demo").step("left", start).step("right", start)

        result = await workflow.run(input=7)

        assert dict(result.outputs) == {"left": "started:7", "right": "started:7"}
        with pytest.raises(WorkflowError, match="produced 2 outputs"):
            _ = result.value

    asyncio.run(scenario())


def test_a_step_reached_by_two_taken_branches_is_rejected() -> None:
    async def scenario() -> None:
        async def start(value: object, context: object) -> str:
            return "started"

        async def join(value: object, context: object) -> object:
            return value

        workflow = (
            Workflow("demo")
            .step("left", start)
            .step("right", start)
            .step("join", join)
            .edge("left", "join")
            .edge("right", "join")
        )

        with pytest.raises(WorkflowExecutionError, match="more than one branch"):
            await workflow.run(input=None)

        assert pending_tasks() == []

    asyncio.run(scenario())


def test_a_step_failure_is_chained_and_reports_earlier_outcomes() -> None:
    async def scenario() -> None:
        async def fine(value: object, context: object) -> str:
            return "fine"

        async def explode(value: object, context: object) -> object:
            raise ValueError("payload contains secret-token")

        workflow = Workflow("demo").step("fine", fine).step("explode", explode)
        workflow = workflow.edge("fine", "explode")

        with pytest.raises(WorkflowExecutionError) as caught:
            await workflow.run()

        error = caught.value
        assert error.step == "explode"
        assert error.workflow == "demo"
        assert isinstance(error.__cause__, ValueError)
        assert "ValueError" in str(error)
        assert "secret-token" not in str(error)
        assert set(error.outcomes) == {"fine"}
        assert error.outcomes["fine"].output == "fine"
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_a_declared_input_type_is_enforced_before_anything_runs() -> None:
    async def scenario() -> None:
        ran: list[str] = []
        events: list[object] = []

        async def only(value: object, context: object) -> object:
            ran.append("only")
            return value

        workflow = Workflow("demo", input_type=str).step("only", only)

        with pytest.raises(WorkflowExecutionError, match="expects input of type str"):
            await workflow.run(input=5, on_event=events.append)

        assert ran == []
        assert events == []

        result = await workflow.run(input="ok")

        assert result.value == "ok"
        assert ran == ["only"]

    asyncio.run(scenario())


def test_a_non_positive_timeout_is_rejected_before_running() -> None:
    async def scenario() -> None:
        ran: list[str] = []

        async def only(value: object, context: object) -> object:
            ran.append("only")
            return value

        workflow = Workflow("demo").step("only", only)

        with pytest.raises(WorkflowValidationError, match="timeout must be greater than zero"):
            await workflow.run(timeout=0)

        assert ran == []

    asyncio.run(scenario())


def test_an_invalid_definition_never_partially_executes() -> None:
    async def scenario() -> None:
        ran: list[str] = []

        async def only(value: object, context: object) -> object:
            ran.append("only")
            return value

        workflow = Workflow("demo").step("only", only).edge("only", "missing")

        with pytest.raises(WorkflowValidationError, match="not a step"):
            await workflow.run()

        assert ran == []

    asyncio.run(scenario())
