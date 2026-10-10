"""Every build-time rule rejects a definition before any step runs."""

from random import Random
from typing import Protocol, runtime_checkable

import pytest

from xyberos import Backoff, Edge, Retry, Step, Workflow, WorkflowValidationError


async def passthrough(value: object, context: object) -> object:
    return value


async def only_input(value: object) -> None:
    return None


async def variadic(*args: object) -> None:
    return None


async def produce_int(value: object, context: object) -> int:
    return 1


async def consume_str(value: str, context: object) -> None:
    return None


async def consume_int(value: int, context: object) -> None:
    return None


def rejects(workflow: Workflow, message: str) -> None:
    with pytest.raises(WorkflowValidationError, match=message):
        workflow.validate()


def branch_source() -> Workflow:
    return (
        Workflow("demo")
        .step("classify", passthrough)
        .step("billing", passthrough)
        .step("general", passthrough)
    )


def test_a_minimal_definition_validates_and_revalidates() -> None:
    workflow = Workflow("demo").step("first", passthrough)

    workflow.validate()
    workflow.validate()


def test_a_branching_definition_with_both_step_kinds_validates() -> None:
    workflow = (
        Workflow("demo", version="2", input_type=str)
        .step("classify", passthrough, timeout=1.0)
        .step("billing", passthrough, retry=Retry(max_attempts=2))
        .step("general", passthrough)
        .step("report", passthrough)
        .edge("classify", "billing", when=lambda value: value == "billing")
        .edge("classify", "general")
        .edge("billing", "report")
        .edge("general", "report")
    )

    workflow.validate()


def test_identity_rules() -> None:
    rejects(Workflow(""), "needs a non-empty name")
    rejects(Workflow("has space"), "must be an identifier")
    rejects(Workflow("demo", version=" "), "needs a non-empty version")


def test_a_workflow_needs_at_least_one_step() -> None:
    rejects(Workflow("demo"), "declares no steps")


def test_step_ids_must_be_present_and_unique() -> None:
    rejects(Workflow("demo").step("", passthrough), "needs a non-empty id")
    rejects(
        Workflow("demo").step("first", passthrough).step("first", passthrough),
        "declares step 'first' more than once",
    )


def test_step_functions_must_be_async() -> None:
    def synchronous(value: object, context: object) -> object:
        return value

    rejects(
        Workflow("demo").step("first", synchronous),  # type: ignore[arg-type]
        "must be an async function",
    )


def test_step_functions_must_accept_the_input_and_the_context() -> None:
    rejects(Workflow("demo").step("first", only_input), "at least 2 positional parameters")


def test_variadic_step_functions_are_accepted() -> None:
    Workflow("demo").step("first", variadic).validate()


def test_step_timeout_must_be_positive() -> None:
    rejects(Workflow("demo").step("first", passthrough, timeout=0), "greater than zero")
    rejects(Workflow("demo").step("first", passthrough, timeout=-1.0), "greater than zero")


def test_step_retry_must_be_a_retry_policy() -> None:
    workflow = Workflow("demo").with_step(
        Step(id="first", run=passthrough, retry="three")  # type: ignore[arg-type]
    )

    rejects(workflow, "retry must be a Retry policy")


def test_retry_policies_reject_invalid_values_on_construction() -> None:
    with pytest.raises(WorkflowValidationError, match="at least 1"):
        Retry(max_attempts=0)
    with pytest.raises(WorkflowValidationError, match="at least one exception type"):
        Retry(retry_on=())
    with pytest.raises(WorkflowValidationError, match="must be exception types"):
        Retry(retry_on=(1,))  # type: ignore[arg-type]


def test_backoff_policies_reject_invalid_values_on_construction() -> None:
    with pytest.raises(WorkflowValidationError, match="initial delay cannot be negative"):
        Backoff(initial=-1)
    with pytest.raises(WorkflowValidationError, match="multiplier must be at least 1"):
        Backoff(multiplier=0.5)
    with pytest.raises(WorkflowValidationError, match="max_delay cannot be negative"):
        Backoff(max_delay=-1)
    with pytest.raises(WorkflowValidationError, match="jitter must be between 0 and 1"):
        Backoff(jitter=2)


def test_backoff_rejects_attempt_numbers_below_one() -> None:
    with pytest.raises(WorkflowValidationError, match="attempt numbers start at 1"):
        Backoff().delay_for(0, random=Random(1))


def test_edges_must_name_declared_steps() -> None:
    rejects(Workflow("demo").step("first", passthrough).edge("first", "missing"), "not a step")
    rejects(Workflow("demo").step("first", passthrough).edge("missing", "first"), "not a step")


def test_self_loops_are_rejected() -> None:
    rejects(Workflow("demo").step("first", passthrough).edge("first", "first"), "is a self-loop")


def test_duplicate_edges_are_rejected() -> None:
    workflow = (
        Workflow("demo")
        .step("first", passthrough)
        .step("second", passthrough)
        .edge("first", "second")
        .edge("first", "second")
    )

    rejects(workflow, "more than once")


def test_only_one_unconditional_edge_can_leave_a_step() -> None:
    rejects(
        branch_source().edge("classify", "billing").edge("classify", "general"),
        "more than one edge without a condition",
    )


def test_the_unconditional_fallback_must_be_declared_last() -> None:
    workflow = (
        branch_source()
        .edge("classify", "general")
        .edge("classify", "billing", when=lambda value: True)
    )

    rejects(workflow, "after its unconditional fallback edge")


def test_branch_conditions_must_be_synchronous() -> None:
    async def asynchronous(value: object) -> bool:
        return True

    rejects(
        branch_source().edge("classify", "billing", when=asynchronous),  # type: ignore[arg-type]
        "must be synchronous",
    )


def test_branch_conditions_take_one_argument_and_must_be_callable() -> None:
    def no_arguments() -> bool:
        return True

    rejects(
        branch_source().edge("classify", "billing", when=no_arguments),  # type: ignore[arg-type]
        "at least 1 positional parameters",
    )
    rejects(
        branch_source().with_edge(Edge("classify", "billing", when="yes")),  # type: ignore[arg-type]
        "must be callable",
    )


def test_cycles_are_reported_with_their_path() -> None:
    workflow = (
        Workflow("demo")
        .step("first", passthrough)
        .step("second", passthrough)
        .edge("first", "second")
        .edge("second", "first")
    )

    rejects(workflow, r"contains a cycle: first -> second -> first")


def test_declared_output_must_be_compatible_with_the_next_declared_input() -> None:
    workflow = (
        Workflow("demo")
        .step("produce", produce_int)
        .step("consume", consume_str)
        .edge("produce", "consume")
    )

    rejects(workflow, r"edge 'produce' -> 'consume' is incompatible")


def test_entry_steps_must_agree_about_the_shared_input() -> None:
    clashing = Workflow("demo").step("by_str", consume_str).step("by_int", consume_int)

    rejects(clashing, "sends the same input to entry steps")


def test_input_type_must_be_usable_with_isinstance() -> None:
    rejects(
        Workflow("demo", input_type=dict[str, int]).step("first", passthrough),
        "must be a class or a tuple of classes",
    )

    class HasArea(Protocol):
        def area(self) -> float: ...

    rejects(
        Workflow("demo", input_type=HasArea).step("first", passthrough),  # type: ignore[arg-type]
        "cannot be used with isinstance",
    )

    @runtime_checkable
    class Checkable(Protocol):
        def area(self) -> float: ...

    checkable = Workflow("demo", input_type=Checkable).step("first", passthrough)  # type: ignore
    checkable.validate()


def test_a_tuple_of_classes_is_accepted_as_the_input_type() -> None:
    Workflow("demo", input_type=(str, bytes)).step("first", passthrough).validate()


def test_input_type_must_be_compatible_with_entry_step_inputs() -> None:
    rejects(
        Workflow("demo", input_type=int).step("consume", consume_str),
        "declares input_type=int",
    )


def test_metadata_must_be_json_serializable_with_string_keys() -> None:
    rejects(
        Workflow("demo", metadata={1: "value"}).step("first", passthrough),
        "keys must be strings",
    )
    rejects(
        Workflow("demo").step("first", passthrough, metadata={"odd": object()}),
        "step 'first' metadata must be JSON-serializable",
    )
    rejects(
        Workflow("demo", metadata={"odd": object()}).step("first", passthrough),
        "workflow 'demo' metadata must be JSON-serializable",
    )
