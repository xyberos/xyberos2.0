"""The scheduler is a pure function: persisted state in, the next action out."""

from __future__ import annotations

from typing import Any

from xyberos.durable.models import StepState
from xyberos.durable.scheduler import PlanKind, plan_next, select_edge
from xyberos.execution import Workflow


async def start(value: object, context: object) -> str:
    return "started"


async def left(value: str, context: object) -> str:
    return f"left:{value}"


async def right(value: str, context: object) -> str:
    return f"right:{value}"


def branching_workflow() -> Workflow:
    return (
        Workflow("branch")
        .step("start", start)
        .step("left", left)
        .step("right", right)
        .edge("start", "left", when=lambda value: value == "left")
        .edge("start", "right")
    )


def test_an_entry_step_is_ready_with_the_run_input() -> None:
    workflow = branching_workflow()

    plan = plan_next(workflow, {"start": StepState.PENDING}, {})

    assert plan.kind is PlanKind.RUN_STEP
    assert plan.step is not None and plan.step.id == "start"
    assert plan.sources == ()


def test_a_successor_is_ready_with_its_source_output() -> None:
    workflow = branching_workflow()
    states = {
        "start": StepState.SUCCEEDED,
        "left": StepState.PENDING,
        "right": StepState.PENDING,
    }

    plan = plan_next(workflow, states, {"start": "left"})

    assert plan.kind is PlanKind.RUN_STEP
    assert plan.step is not None and plan.step.id == "left"
    assert plan.sources == ("start",)
    assert plan.value == "left"


def test_a_branch_that_was_not_taken_is_skipped() -> None:
    workflow = branching_workflow()
    states = {
        "start": StepState.SUCCEEDED,
        "left": StepState.SKIPPED,
        "right": StepState.PENDING,
    }

    plan = plan_next(workflow, states, {"start": "right"})

    assert plan.kind is PlanKind.RUN_STEP
    assert plan.step is not None and plan.step.id == "right"


def test_a_step_no_branch_reached_is_reported_for_skipping() -> None:
    workflow = branching_workflow()
    states = {
        "start": StepState.SUCCEEDED,
        "left": StepState.PENDING,
        "right": StepState.PENDING,
    }

    plan = plan_next(workflow, states, {"start": "neither"})

    assert plan.kind is PlanKind.SKIP_STEP
    assert plan.step is not None and plan.step.id == "left"
    assert plan.reason == "no branch reached this step"


def test_a_resolved_workflow_is_ready_to_complete() -> None:
    workflow = branching_workflow()
    states = {
        "start": StepState.SUCCEEDED,
        "left": StepState.SUCCEEDED,
        "right": StepState.SKIPPED,
    }

    plan = plan_next(workflow, states, {"start": "left", "left": "left:started"})

    assert plan.kind is PlanKind.COMPLETE
    assert plan.outputs == {"left": "left:started"}


def test_two_taken_branches_into_one_step_is_a_conflict() -> None:
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
    states = {
        "left": StepState.SUCCEEDED,
        "right": StepState.SUCCEEDED,
        "join": StepState.PENDING,
    }

    plan = plan_next(workflow, states, {"left": "left", "right": "right"})

    assert plan.kind is PlanKind.CONFLICT
    assert plan.sources == ("left", "right")
    assert "more than one branch" in plan.reason


def test_a_predicate_selects_the_first_matching_edge() -> None:
    workflow = branching_workflow()
    outgoing = workflow.outgoing("start")

    selected: Any = select_edge(outgoing, "left")
    assert selected is not None and selected.target == "left"
    fallback = select_edge(outgoing, "something else")
    assert fallback is not None and fallback.target == "right"
