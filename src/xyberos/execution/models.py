"""Immutable workflow definitions and execution results.

A definition is a value: every builder method returns a new :class:`Workflow`, metadata is frozen,
and nothing is mutated once validation succeeds. That is what lets a definition be inspected,
logged, compared in a test, and persisted later without the executor's involvement.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeAlias

from xyberos.errors import WorkflowError, WorkflowValidationError
from xyberos.execution.events import EventSink
from xyberos.execution.policies import CancellationToken, Retry

if TYPE_CHECKING:
    from xyberos.execution.executor import WorkflowExecutor

StepFunction: TypeAlias = Callable[..., Coroutine[Any, Any, Any]]
"""A step function, called as ``await run(value, context)``."""

BranchPredicate: TypeAlias = Callable[[Any], bool]
"""A synchronous predicate over the output of the step an edge leaves."""

InputType: TypeAlias = type[Any] | tuple[type[Any], ...]
"""A class or tuple of classes usable with ``isinstance`` to declare a workflow's input."""

DIRECT_WORKFLOW = "(direct)"
"""The workflow name reported by direct calls, which have no definition."""


class StepStatus(str, Enum):
    """How one step ended."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


def _freeze(values: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise WorkflowValidationError(f"metadata must be a mapping, got {type(values).__name__}")
    return MappingProxyType(dict(values))


def _render_seconds(value: float) -> str:
    return f"{value:g}s"


def _callable_name(value: object) -> str:
    return getattr(value, "__name__", type(value).__name__)


def _render_types(value: InputType) -> str:
    if isinstance(value, tuple):
        return ", ".join(item.__name__ for item in value)
    return value.__name__


@dataclass(frozen=True)
class Step:
    """One unit of work in a workflow.

    ``timeout`` bounds a single attempt in seconds, not the whole step, so a retried step gets a
    fresh timeout per attempt. ``metadata`` must stay JSON-serializable and free of secrets,
    because it is part of the definition that inspection, tests, and later phases read.
    """

    id: str
    run: StepFunction
    retry: Retry | None = None
    timeout: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def describe_policies(self) -> str:
        """Return this step's policies as one line, or an empty string when it has none."""
        details = []
        if self.retry is not None:
            names = ", ".join(item.__name__ for item in self.retry.retry_on)
            backoff = self.retry.backoff
            details.append(
                f"retry(max_attempts={self.retry.max_attempts}, retry_on=({names}), "
                f"backoff(initial={backoff.initial:g}, multiplier={backoff.multiplier:g}, "
                f"max_delay={backoff.max_delay:g}, jitter={backoff.jitter:g}))"
            )
        if self.timeout is not None:
            details.append(f"timeout={_render_seconds(self.timeout)}")
        if self.metadata:
            details.append("metadata=set")
        return " ".join(details)

    def render(self) -> str:
        """Return a single-line description of this step."""
        policies = self.describe_policies()
        suffix = f"  {policies}" if policies else ""
        return f"{self.id} run={_callable_name(self.run)}{suffix}"


@dataclass(frozen=True)
class Edge:
    """A directed connection that also carries data.

    An edge means "the target receives the source's output, and only once the source resolved".
    ``when`` turns the edge into a branch condition evaluated against the source's output; the one
    edge without a condition is the fallback and must be declared last for its source.
    """

    source: str
    target: str
    when: BranchPredicate | None = None

    def render(self) -> str:
        """Return a single-line description of this edge."""
        condition = ""
        if self.when is not None:
            condition = f" when={_callable_name(self.when)}"
        return f"{self.source} -> {self.target}{condition}"


@dataclass(frozen=True)
class Attempt:
    """The outcome of one attempt at one step."""

    number: int
    status: StepStatus
    duration: float
    error_type: str | None = None


@dataclass(frozen=True)
class StepOutcome:
    """The outcome of one step, including every attempt it made."""

    step: str
    status: StepStatus
    attempts: tuple[Attempt, ...] = ()
    output: object = None
    duration: float = 0.0
    error_type: str | None = None

    @property
    def attempt_count(self) -> int:
        """How many attempts the step made."""
        return len(self.attempts)


@dataclass(frozen=True)
class WorkflowResult:
    """What a successful run produced.

    ``outputs`` holds the output of each exit step that ran, keyed by step id, so a branching
    workflow can report several results. ``steps`` holds every resolved step, including skipped
    ones; steps that never started are absent.
    """

    workflow: str
    version: str
    outputs: Mapping[str, object]
    steps: Mapping[str, StepOutcome]
    duration: float

    def outcome(self, step_id: str) -> StepOutcome:
        """Return one step's outcome.

        A completed run reports every declared step, so a missing id is a caller mistake and raises;
        use ``result.steps.get(step_id)`` for a lookup that tolerates absence.
        """
        outcome = self.steps.get(step_id)
        if outcome is None:
            resolved = ", ".join(sorted(self.steps)) or "none"
            raise WorkflowError(
                f"workflow {self.workflow!r} has no outcome for step {step_id!r}; "
                f"resolved steps: {resolved}"
            )
        return outcome

    @property
    def value(self) -> object:
        """Return the single exit output, or raise when this run produced several."""
        if len(self.outputs) != 1:
            names = ", ".join(sorted(self.outputs)) or "none"
            raise WorkflowError(
                f"workflow {self.workflow!r} produced {len(self.outputs)} outputs ({names}); "
                "use result.outputs to read them by step"
            )
        return next(iter(self.outputs.values()))


@dataclass(frozen=True)
class Workflow:
    """An immutable, inspectable multi-step definition.

    Build one fluently, then run it::

        workflow = (
            Workflow("support", version="1")
            .step("retrieve", retrieve_documents, retry=Retry(max_attempts=3))
            .step("answer", generate_answer, timeout=seconds(30))
            .edge("retrieve", "answer")
        )
        result = await workflow.run(input=request_data, timeout=seconds(45))

    Execution is sequential and may branch: a step runs once every step feeding it has resolved,
    receives the output of the one branch that reached it, and is skipped when no branch did.
    """

    name: str
    version: str = "1"
    input_type: InputType | None = None
    steps: tuple[Step, ...] = ()
    edges: tuple[Edge, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    _validated: bool = field(default=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def step(
        self,
        step_id: str,
        run: StepFunction,
        *,
        retry: Retry | None = None,
        timeout: float | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Workflow:
        """Return a new definition with one more step appended."""
        return self.with_step(
            Step(id=step_id, run=run, retry=retry, timeout=timeout, metadata=metadata or {})
        )

    def with_step(self, step: Step) -> Workflow:
        """Return a new definition with ``step`` appended."""
        return replace(self, steps=(*self.steps, step), _validated=False)

    def edge(
        self,
        source: str,
        target: str,
        *,
        when: BranchPredicate | None = None,
    ) -> Workflow:
        """Return a new definition with one more edge appended."""
        return self.with_edge(Edge(source=source, target=target, when=when))

    def with_edge(self, edge: Edge) -> Workflow:
        """Return a new definition with ``edge`` appended."""
        return replace(self, edges=(*self.edges, edge), _validated=False)

    @property
    def step_ids(self) -> tuple[str, ...]:
        """Return every step id in declaration order."""
        return tuple(step.id for step in self.steps)

    @property
    def entries(self) -> tuple[Step, ...]:
        """Return the steps that start the workflow, in declaration order."""
        return tuple(step for step in self.steps if not self.incoming(step.id))

    @property
    def exits(self) -> tuple[Step, ...]:
        """Return the steps whose output ends the workflow, in declaration order."""
        return tuple(step for step in self.steps if not self.outgoing(step.id))

    def step_by_id(self, step_id: str) -> Step:
        """Return one declared step."""
        for step in self.steps:
            if step.id == step_id:
                return step
        declared = ", ".join(self.step_ids) or "none"
        raise WorkflowValidationError(
            f"workflow {self.name!r} has no step {step_id!r}; declared steps: {declared}"
        )

    def outgoing(self, step_id: str) -> tuple[Edge, ...]:
        """Return the edges leaving ``step_id`` in declaration order."""
        return tuple(edge for edge in self.edges if edge.source == step_id)

    def incoming(self, step_id: str) -> tuple[Edge, ...]:
        """Return the edges entering ``step_id`` in declaration order."""
        return tuple(edge for edge in self.edges if edge.target == step_id)

    def render(self) -> str:
        """Return a deterministic description of the graph, policies, and version.

        Rendering never calls a step function or a branch predicate, so it is safe in logs, tests,
        and documentation.
        """
        lines = [f"workflow {self.name!r} version={self.version!r}"]
        if self.input_type is not None:
            lines.append(f"  input: {_render_types(self.input_type)}")
        exit_names = ", ".join(step.id for step in self.exits) or "none"
        lines.append(f"  exits: {exit_names}")
        for step in self.steps:
            markers = []
            if not self.incoming(step.id):
                markers.append("entry")
            if not self.outgoing(step.id):
                markers.append("exit")
            marker = f"  [{','.join(markers)}]" if markers else ""
            policies = step.describe_policies()
            detail = f"  {policies}" if policies else ""
            lines.append(f"  step {step.id}{marker}  run={_callable_name(step.run)}{detail}")
        for edge in self.edges:
            lines.append(f"  edge {edge.render()}")
        return "\n".join(lines)

    def validate(self) -> None:
        """Check the definition and remember that the check passed.

        Validation is idempotent and free of side effects apart from that memo. Changing a
        definition means building a new one, which starts unvalidated again.
        """
        if self._validated:
            return
        from xyberos.execution.validation import validate_workflow

        validate_workflow(self)
        object.__setattr__(self, "_validated", True)

    async def run(
        self,
        input: object = None,
        *,
        timeout: float | None = None,
        cancellation: CancellationToken | None = None,
        on_event: EventSink | None = None,
        executor: WorkflowExecutor | None = None,
    ) -> WorkflowResult:
        """Execute this definition and return its result.

        ``timeout`` is the whole run's budget in seconds; the absolute deadline derived from it is
        what the execution context exposes. Retries, cancellation, events, and clock injection all
        belong to the executor, which is created on demand unless one is supplied.
        """
        from xyberos.execution.executor import WorkflowExecutor as _Executor

        active = executor if executor is not None else _Executor()
        return await active.run(
            self,
            input=input,
            timeout=timeout,
            cancellation=cancellation,
            on_event=on_event,
        )
