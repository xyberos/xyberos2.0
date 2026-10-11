"""Which step runs next, decided from persisted state alone.

The durable executor does not keep a scheduler in memory: after a crash there is nothing to keep.
Every claim re-derives the next action from the definition plus the persisted step states, which is
why this module is a pure function over those two inputs and has no I/O at all.

The rules are the in-process engine's rules, restated for a world where some steps are already
resolved:

* a step runs when every source that feeds it has resolved and exactly one of those edges was taken;
* a step whose sources resolved but none of them reached it is *skipped*;
* two taken edges into one step is a definition bug and stops the run with both sources named;
* the run completes when no step is left to decide, and its result is the outputs of the exit steps.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from xyberos.durable.models import StepState, step_is_terminal
from xyberos.errors import DurableStateError
from xyberos.execution.models import Edge, Step, Workflow


class PlanKind(str, Enum):
    """What the worker should do next."""

    RUN_STEP = "run_step"
    SKIP_STEP = "skip_step"
    COMPLETE = "complete"
    CONFLICT = "conflict"
    NEEDS_DECISION = "needs_decision"


@dataclass(frozen=True)
class Plan:
    """One decision about one execution."""

    kind: PlanKind
    step: Step | None = None
    value: object = None
    outputs: Mapping[str, object] | None = None
    sources: tuple[str, ...] = ()
    reason: str = ""


def plan_next(
    workflow: Workflow,
    states: Mapping[str, StepState],
    outputs: Mapping[str, object],
) -> Plan:
    """Return the next action for an execution, given its persisted step states and outputs.

    ``outputs`` maps a *succeeded* step id to its persisted output, which is what branch predicates
    are evaluated against.

    A step left ``OUTCOME_UNKNOWN`` stops the decision immediately. That state exists precisely
    because re-running the step is not known to be safe, so the scheduler must never hand it out as
    work: it reports ``NEEDS_DECISION`` and lets a person or a reconciler say what happened.
    """
    taken = _taken_edges(workflow, states, outputs)
    undecided = False
    for step in workflow.steps:
        state = states.get(step.id, StepState.PENDING)
        if step_is_terminal(state):
            continue
        if state is StepState.OUTCOME_UNKNOWN:
            return Plan(
                kind=PlanKind.NEEDS_DECISION,
                step=step,
                reason=(
                    f"step {step.id!r} has an unresolved attempt: whether its effect happened is "
                    "unknown, so it must be reconciled or explicitly repeated before the run "
                    "continues"
                ),
            )
        incoming = workflow.incoming(step.id)
        reached = tuple(edge.source for edge in incoming if (edge.source, edge.target) in taken)
        if len(reached) > 1:
            return Plan(
                kind=PlanKind.CONFLICT,
                step=step,
                sources=tuple(sorted(reached)),
                reason=(
                    f"step {step.id!r} was reached by more than one branch "
                    f"({', '.join(sorted(reached))}); branches that merge into one step must be "
                    "mutually exclusive"
                ),
            )
        unresolved = [
            edge.source
            for edge in incoming
            if not step_is_terminal(states.get(edge.source, StepState.PENDING))
        ]
        if unresolved:
            # A source is still to come. With a validated acyclic definition, deciding the steps in
            # declaration order means this only happens while an earlier step is still open.
            undecided = True
            continue
        if incoming and not reached:
            return Plan(
                kind=PlanKind.SKIP_STEP,
                step=step,
                reason="no branch reached this step",
            )
        if not incoming:
            return Plan(kind=PlanKind.RUN_STEP, step=step, value=None)
        source = reached[0]
        return Plan(
            kind=PlanKind.RUN_STEP,
            step=step,
            value=outputs.get(source),
            sources=(source,),
        )
    if undecided:
        raise DurableStateError(
            f"workflow {workflow.name!r} has undecided steps but nothing is ready; the persisted "
            "step states cannot be completed, which means the journal and the definition disagree"
        )
    return Plan(
        kind=PlanKind.COMPLETE,
        outputs={step.id: outputs.get(step.id) for step in workflow.exits if step.id in outputs},
        reason="every step resolved",
    )


def _taken_edges(
    workflow: Workflow,
    states: Mapping[str, StepState],
    outputs: Mapping[str, object],
) -> set[tuple[str, str]]:
    """Return the edges a resolved step selected, using the same rules as the in-process engine."""
    taken: set[tuple[str, str]] = set()
    for step in workflow.steps:
        if states.get(step.id, StepState.PENDING) is not StepState.SUCCEEDED:
            continue
        selected = select_edge(workflow.outgoing(step.id), outputs.get(step.id))
        if selected is not None:
            taken.add((selected.source, selected.target))
    return taken


def select_edge(outgoing: tuple[Edge, ...], output: object) -> Edge | None:
    """Return the single edge a step's output selects, or ``None`` when no branch matched.

    Conditional edges are considered in declaration order and the unconditional fallback is
    validated to come last, so at most one branch is ever taken.
    """
    for edge in outgoing:
        if edge.when is None:
            return edge
        if edge.when(output):
            return edge
    return None
