"""Definitions are immutable values that can be inspected without executing anything."""

import pytest

from xyberos import (
    Retry,
    Step,
    StepOutcome,
    StepStatus,
    Workflow,
    WorkflowError,
    WorkflowResult,
    WorkflowValidationError,
    seconds,
)


async def passthrough(value: object, context: object) -> object:
    """A minimal async step used to build definitions."""
    return value


def test_builder_returns_new_definitions_and_leaves_the_original_unchanged() -> None:
    base = Workflow("demo")
    built = base.step("first", passthrough).edge("first", "second")

    assert base.steps == ()
    assert base.edges == ()
    assert built is not base
    assert built.step_ids == ("first",)


def test_metadata_is_frozen_and_disconnected_from_the_caller() -> None:
    source = {"owner": "team"}

    workflow = Workflow("demo", metadata=source)
    step = Step(id="first", run=passthrough, metadata=source)
    source["owner"] = "someone else"

    assert dict(workflow.metadata) == {"owner": "team"}
    assert dict(step.metadata) == {"owner": "team"}
    with pytest.raises(TypeError):
        workflow.metadata["owner"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        step.metadata["owner"] = "mutated"  # type: ignore[index]


def test_metadata_must_be_a_mapping() -> None:
    with pytest.raises(WorkflowValidationError, match="metadata must be a mapping"):
        Step(id="first", run=passthrough, metadata=["not", "a", "mapping"])  # type: ignore[arg-type]


def test_graph_views_report_entries_exits_and_endpoints() -> None:
    workflow = (
        Workflow("demo")
        .step("first", passthrough)
        .step("second", passthrough)
        .step("third", passthrough)
        .edge("first", "second")
        .edge("second", "third")
    )

    assert workflow.entries == (workflow.step_by_id("first"),)
    assert workflow.exits == (workflow.step_by_id("third"),)
    assert workflow.incoming("first") == ()
    assert [edge.target for edge in workflow.outgoing("second")] == ["third"]
    assert [edge.source for edge in workflow.incoming("second")] == ["first"]


def test_step_by_id_reports_an_unknown_step() -> None:
    workflow = Workflow("demo").step("first", passthrough)

    with pytest.raises(WorkflowValidationError, match="no step 'missing'"):
        workflow.step_by_id("missing")


def test_render_describes_the_graph_without_executing_it() -> None:
    calls: list[str] = []

    async def handler(value: object, context: object) -> object:
        calls.append("handler")
        return value

    workflow = (
        Workflow("demo", version="7", input_type=str)
        .step("first", handler, retry=Retry(max_attempts=2), timeout=seconds(30))
        .step("second", handler, metadata={"owner": "team"})
        .edge("first", "second")
    )

    rendered = workflow.render()

    assert rendered == workflow.render()
    assert rendered.splitlines()[0] == "workflow 'demo' version='7'"
    assert "input: str" in rendered
    assert "exits: second" in rendered
    assert "step first  [entry]  run=handler  retry(max_attempts=2" in rendered
    assert "timeout=30s" in rendered
    assert "step second  [exit]  run=handler  metadata=set" in rendered
    assert "edge first -> second" in rendered
    assert calls == []


def test_render_reports_branch_conditions_by_name() -> None:
    workflow = (
        Workflow("demo")
        .step("classify", passthrough)
        .step("billing", passthrough)
        .step("general", passthrough)
        .edge("classify", "billing", when=lambda value: value == "billing")
        .edge("classify", "general")
    )

    rendered = workflow.render()

    assert "edge classify -> billing when=<lambda>" in rendered
    assert "edge classify -> general" in rendered


def test_editing_a_validated_definition_invalidates_the_memo() -> None:
    workflow = Workflow("demo").step("first", passthrough)
    workflow.validate()

    edited = workflow.step("second", lambda value, context: None)  # type: ignore[arg-type]

    with pytest.raises(WorkflowValidationError, match="must be an async function"):
        edited.validate()


def test_validation_is_idempotent() -> None:
    workflow = Workflow("demo").step("first", passthrough)

    workflow.validate()
    workflow.validate()

    assert workflow._validated is True


def test_result_value_requires_a_single_output() -> None:
    single = WorkflowResult(
        workflow="demo", version="1", outputs={"a": "only"}, steps={}, duration=0.1
    )
    multiple = WorkflowResult(
        workflow="demo", version="1", outputs={"a": 1, "b": 2}, steps={}, duration=0.1
    )

    assert single.value == "only"
    with pytest.raises(WorkflowError, match="produced 2 outputs"):
        _ = multiple.value


def test_result_reports_step_outcomes_by_id() -> None:
    outcome = StepOutcome(step="first", status=StepStatus.SKIPPED)
    result = WorkflowResult(
        workflow="demo", version="1", outputs={}, steps={"first": outcome}, duration=0.0
    )

    assert result.outcome("first") is outcome
    assert result.steps.get("missing") is None
    with pytest.raises(WorkflowError, match="no outcome for step 'missing'"):
        result.outcome("missing")
