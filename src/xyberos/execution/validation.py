"""Build-time validation of a workflow definition.

Validation is the only place a definition is rejected, which is what lets the executor run a
graph without re-checking it. Every rule is decidable from the definition alone: nothing here
calls a step function or a branch predicate, so validating is free of side effects.

One structural guarantee follows from the rules rather than needing its own check: because a
definition must declare at least one step and must be acyclic, every step is reachable from an
entry step (a step with no incoming edge) and every step can reach an exit step (a step with no
outgoing edge).
"""

from __future__ import annotations

import inspect
import json
import types
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any, Union, get_args, get_origin, get_type_hints

from xyberos.errors import WorkflowValidationError
from xyberos.execution.models import Step, Workflow
from xyberos.execution.policies import Retry


def validate_workflow(workflow: Workflow) -> None:
    """Raise :class:`WorkflowValidationError` unless ``workflow`` is executable."""
    _validate_identity(workflow)
    _validate_steps(workflow)
    _validate_edges(workflow)
    _validate_acyclic(workflow)
    _validate_declared_types(workflow)
    _validate_metadata(workflow)


def _validate_identity(workflow: Workflow) -> None:
    name = workflow.name
    if not isinstance(name, str) or not name.strip():
        raise WorkflowValidationError("a workflow needs a non-empty name")
    if not name.replace("-", "_").isidentifier():
        raise WorkflowValidationError(
            f"workflow name {name!r} must be an identifier so events and configuration can name it"
        )
    if not isinstance(workflow.version, str) or not workflow.version.strip():
        raise WorkflowValidationError(
            f"workflow {name!r} needs a non-empty version: a definition is versioned because a "
            "durable executor records the version it ran"
        )


def _validate_steps(workflow: Workflow) -> None:
    if not workflow.steps:
        raise WorkflowValidationError(f"workflow {workflow.name!r} declares no steps")
    seen: set[str] = set()
    for step in workflow.steps:
        step_id = step.id
        if not isinstance(step_id, str) or not step_id.strip():
            raise WorkflowValidationError(
                f"every step of workflow {workflow.name!r} needs a non-empty id"
            )
        if step_id in seen:
            raise WorkflowValidationError(
                f"workflow {workflow.name!r} declares step {step_id!r} more than once"
            )
        seen.add(step_id)
        _validate_step_callable(step)
        if step.timeout is not None and step.timeout <= 0:
            raise WorkflowValidationError(
                f"step {step_id!r} timeout must be greater than zero, got {step.timeout!r}"
            )
        if step.retry is not None and not isinstance(step.retry, Retry):
            raise WorkflowValidationError(
                f"step {step_id!r} retry must be a Retry policy, got {type(step.retry).__name__}"
            )


def _validate_step_callable(step: Step) -> None:
    run = step.run
    if not callable(run):
        raise WorkflowValidationError(
            f"step {step.id!r} needs a callable, got {type(run).__name__}"
        )
    if not inspect.iscoroutinefunction(run):
        raise WorkflowValidationError(
            f"step {step.id!r} must be an async function: blocking or CPU-bound work would stall "
            "the event loop and could not be cancelled; await asyncio.to_thread(...) inside an "
            "async step instead"
        )
    _require_parameters(run, 2, f"the function of step {step.id!r}")


def _validate_edges(workflow: Workflow) -> None:
    declared = set(workflow.step_ids)
    seen: set[tuple[str, str]] = set()
    fallback_declared: set[str] = set()
    for edge in workflow.edges:
        for role, value in (("source", edge.source), ("target", edge.target)):
            if value not in declared:
                raise WorkflowValidationError(
                    f"edge {edge.source!r} -> {edge.target!r} names {role} {value!r}, which is not "
                    f"a step of workflow {workflow.name!r}"
                )
        if edge.source == edge.target:
            raise WorkflowValidationError(
                f"edge {edge.source!r} -> {edge.target!r} is a self-loop; cycles are not supported"
            )
        pair = (edge.source, edge.target)
        if pair in seen:
            raise WorkflowValidationError(
                f"workflow {workflow.name!r} declares the edge "
                f"{edge.source!r} -> {edge.target!r} more than once"
            )
        seen.add(pair)
        if edge.when is None:
            if edge.source in fallback_declared:
                raise WorkflowValidationError(
                    f"step {edge.source!r} has more than one edge without a condition; only one "
                    "unconditional edge can act as the fallback"
                )
            fallback_declared.add(edge.source)
            continue
        if not callable(edge.when):
            raise WorkflowValidationError(
                f"the branch condition on {edge.source!r} -> {edge.target!r} must be callable"
            )
        if inspect.iscoroutinefunction(edge.when):
            raise WorkflowValidationError(
                f"the branch condition on {edge.source!r} -> {edge.target!r} must be synchronous: "
                "the executor evaluates conditions before the step's output is passed on"
            )
        _require_parameters(
            edge.when, 1, f"the branch condition on {edge.source!r} -> {edge.target!r}"
        )
        if edge.source in fallback_declared:
            raise WorkflowValidationError(
                f"step {edge.source!r} declares the branch condition "
                f"{edge.source!r} -> {edge.target!r} after its unconditional fallback edge; "
                "declare conditional edges first so the fallback is considered last"
            )


def _validate_acyclic(workflow: Workflow) -> None:
    successors: dict[str, list[str]] = {step_id: [] for step_id in workflow.step_ids}
    indegree: dict[str, int] = {step_id: 0 for step_id in workflow.step_ids}
    for edge in workflow.edges:
        successors[edge.source].append(edge.target)
        indegree[edge.target] += 1
    ready = deque(step_id for step_id in workflow.step_ids if indegree[step_id] == 0)
    visited = 0
    while ready:
        current = ready.popleft()
        visited += 1
        for target in successors[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(workflow.step_ids):
        remaining = {step_id for step_id, count in indegree.items() if count > 0}
        cycle = _describe_cycle(successors, remaining)
        raise WorkflowValidationError(
            f"workflow {workflow.name!r} contains a cycle: {cycle}; sequential and conditional "
            "execution does not support loops"
        )


def _describe_cycle(successors: Mapping[str, list[str]], remaining: set[str]) -> str:
    start = next(iter(sorted(remaining)))
    path = [start]
    positions = {start: 0}
    current = start
    while True:
        following = [target for target in successors[current] if target in remaining]
        if not following:
            return " -> ".join(path)
        candidate = following[0]
        if candidate in positions:
            return " -> ".join([*path[positions[candidate] :], candidate])
        positions[candidate] = len(path)
        path.append(candidate)
        current = candidate


def _validate_declared_types(workflow: Workflow) -> None:
    if workflow.input_type is not None:
        _require_isinstance_capable(workflow.input_type, f"workflow {workflow.name!r} input_type")
    declared = {step.id: _declared_signature(step.run) for step in workflow.steps}
    _require_compatible_inputs(
        {step.id: declared[step.id][0] for step in workflow.entries},
        workflow,
    )
    input_type = workflow.input_type
    if input_type is not None:
        for step in workflow.entries:
            declared_input = declared[step.id][0]
            if declared_input is not None and not _compatible(input_type, declared_input):
                raise WorkflowValidationError(
                    f"entry step {step.id!r} declares an input of {_describe(declared_input)} but "
                    f"workflow {workflow.name!r} declares input_type={_describe(input_type)}"
                )
    for edge in workflow.edges:
        source_output = declared[edge.source][1]
        target_input = declared[edge.target][0]
        if _compatible(source_output, target_input):
            continue
        raise WorkflowValidationError(
            f"edge {edge.source!r} -> {edge.target!r} is incompatible: step {edge.source!r} "
            f"declares {_describe(source_output)} while step {edge.target!r} declares "
            f"{_describe(target_input)}"
        )


def _require_compatible_inputs(
    declared_inputs: Mapping[str, object | None],
    workflow: Workflow,
) -> None:
    reference: tuple[str, object] | None = None
    for step_id, declared_input in declared_inputs.items():
        if declared_input is None:
            continue
        if reference is None:
            reference = (step_id, declared_input)
            continue
        if not _compatible(reference[1], declared_input):
            raise WorkflowValidationError(
                f"workflow {workflow.name!r} sends the same input to entry steps "
                f"{reference[0]!r} and {step_id!r}, which declare {_describe(reference[1])} and "
                f"{_describe(declared_input)}"
            )


def _validate_metadata(workflow: Workflow) -> None:
    _require_serializable(dict(workflow.metadata), f"workflow {workflow.name!r} metadata")
    for step in workflow.steps:
        _require_serializable(dict(step.metadata), f"step {step.id!r} metadata")


def _require_serializable(values: Mapping[str, object], label: str) -> None:
    for key in values:
        if not isinstance(key, str):
            raise WorkflowValidationError(f"{label} keys must be strings, got {key!r}")
    try:
        json.dumps(values, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise WorkflowValidationError(f"{label} must be JSON-serializable: {error}") from error


def _require_isinstance_capable(value: object, label: str) -> None:
    candidates: tuple[object, ...] = value if isinstance(value, tuple) else (value,)
    resolved: list[type[object]] = []
    for item in candidates:
        if not isinstance(item, type):
            raise WorkflowValidationError(
                f"{label} must be a class or a tuple of classes usable with isinstance, "
                f"got {value!r}"
            )
        resolved.append(item)
    if not resolved:
        raise WorkflowValidationError(f"{label} must name at least one class")
    try:
        isinstance(None, tuple(resolved))
    except TypeError as error:
        raise WorkflowValidationError(f"{label} cannot be used with isinstance: {error}") from error


def _require_parameters(func: Callable[..., Any], count: int, label: str) -> None:
    try:
        parameters = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return
    positional = 0
    variadic = False
    for parameter in parameters:
        if parameter.kind is parameter.VAR_POSITIONAL:
            variadic = True
        elif parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD):
            positional += 1
    if not variadic and positional < count:
        raise WorkflowValidationError(
            f"{label} must accept at least {count} positional parameters, the declared input and "
            f"the execution context, but accepts {positional}"
        )


def _declared_signature(func: Callable[..., Any]) -> tuple[object | None, object | None]:
    """Return a step's declared input and output, treating anything unresolvable as undeclared."""
    try:
        hints = get_type_hints(func, include_extras=False)
    except Exception:  # a forward reference that cannot resolve is not a definition error
        return None, None
    declared_output = hints.get("return")
    declared_input = None
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return None, declared_output
    for name, parameter in parameters.items():
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD):
            declared_input = hints.get(name)
            break
    return declared_input, declared_output


def _compatible(source: object | None, target: object | None) -> bool:
    """Return whether an output of ``source`` can feed an input of ``target``.

    The check is deliberately conservative: it rejects only a provable mismatch between two
    declared classes, or between parameterised generics with unrelated origins. Anything it cannot
    decide, including an unannotated value, ``Any``, or an exotic typing construct, is accepted,
    because wrongly rejecting a valid workflow is worse than missing a mismatch.
    """
    if source is None or target is None or source is Any or target is Any or source == target:
        return True
    source_members = _union_members(source)
    if source_members:
        return all(_compatible(member, target) for member in source_members)
    target_members = _union_members(target)
    if target_members:
        return any(_compatible(source, member) for member in target_members)
    source_origin = get_origin(source) or source
    target_origin = get_origin(target) or target
    if isinstance(source_origin, type) and isinstance(target_origin, type):
        return issubclass(source_origin, target_origin) or issubclass(target_origin, source_origin)
    return True


def _union_members(value: object | None) -> tuple[object, ...]:
    origin = get_origin(value)
    if origin is Union or origin is types.UnionType:
        return get_args(value)
    return ()


def _describe(value: object) -> str:
    if isinstance(value, tuple):
        return " | ".join(_describe(item) for item in value)
    return getattr(value, "__name__", repr(value))
