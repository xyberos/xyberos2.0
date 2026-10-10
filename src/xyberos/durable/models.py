"""Persisted execution state: statuses, the transition table, and inspection records.

The transition table is the contract a worker cannot talk its way out of: every status change goes
through :func:`require_execution_transition` or :func:`require_step_transition` before it reaches
SQL, so an illegal transition is a programming error rather than a row nobody can interpret.

Durable status names are deliberately distinct from the in-process engine's ``StepStatus``: the
durable executor persists across restarts, so its states answer "what survives a crash", not "what
happened during one call".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from xyberos.errors import DurableStateError


class ExecutionStatus(str, Enum):
    """Where a durable execution stands.

    ``RETRYING`` means an attempt is scheduled and will be claimed automatically. ``WAITING`` means
    the execution is parked until something outside the worker acts — an operator decision or an
    external signal — so no claim is eligible.
    """

    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class StepState(str, Enum):
    """Where one step of a durable execution stands.

    ``OUTCOME_UNKNOWN`` means an attempt was interrupted after it may have produced its external
    effect and before its result was persisted. It is never inferred: recovery records it explicitly
    when it cannot prove what happened.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class FailureKind(str, Enum):
    """Why an execution stopped, in a form an operator can act on."""

    STEP_FAILED = "step_failed"
    INCOMPATIBLE_DEFINITION = "incompatible_definition"
    DEFINITION_CONFLICT = "definition_conflict"
    OUTCOME_UNKNOWN = "outcome_unknown"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class EventKind(str, Enum):
    """Durable journal events, in the order they are appended."""

    SUBMITTED = "submitted"
    CLAIMED = "claimed"
    LEASE_RENEWED = "lease_renewed"
    RECOVERED = "recovered"
    STEP_STARTED = "step_started"
    STEP_SUCCEEDED = "step_succeeded"
    STEP_SKIPPED = "step_skipped"
    STEP_FAILED = "step_failed"
    STEP_OUTCOME_UNKNOWN = "step_outcome_unknown"
    RETRY_SCHEDULED = "retry_scheduled"
    YIELDED = "yielded"
    CANCELLATION_REQUESTED = "cancellation_requested"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_EXECUTION_STATES = frozenset(
    {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    }
)

TERMINAL_STEP_STATES = frozenset({StepState.SUCCEEDED, StepState.SKIPPED, StepState.FAILED})

# Eligibility is defined by the claim query; this set is what an operator sees as "claimable".
CLAIMABLE_EXECUTION_STATES = frozenset({ExecutionStatus.PENDING, ExecutionStatus.RETRYING})

EXECUTION_TRANSITIONS: Mapping[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.PENDING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.FAILED,
        }
    ),
    # RUNNING -> RUNNING is recovery: an expired lease is re-claimed by a new owner and a strictly
    # higher fencing token, which is the only way a status may be "set" to what it already is.
    # RUNNING -> PENDING is a worker yielding after finishing its unit of work: the execution is
    # ready for its next step and belongs to nobody, so it can be claimed again (and by anyone).
    ExecutionStatus.RUNNING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.PENDING,
            ExecutionStatus.RETRYING,
            ExecutionStatus.WAITING,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
        }
    ),
    ExecutionStatus.RETRYING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.WAITING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
        }
    ),
    ExecutionStatus.WAITING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
        }
    ),
    ExecutionStatus.COMPLETED: frozenset(),
    ExecutionStatus.FAILED: frozenset(),
    ExecutionStatus.CANCELLED: frozenset(),
    ExecutionStatus.TIMED_OUT: frozenset(),
}

STEP_TRANSITIONS: Mapping[StepState, frozenset[StepState]] = {
    StepState.PENDING: frozenset(
        {
            StepState.RUNNING,
            StepState.SKIPPED,
            StepState.FAILED,
            StepState.OUTCOME_UNKNOWN,
        }
    ),
    # A failed or interrupted attempt returns the step to PENDING with a scheduled retry, so the
    # step's own state never encodes "waiting to retry": the schedule does. RUNNING -> RUNNING is
    # the recovery re-claim of an attempt whose result never reached the journal.
    StepState.RUNNING: frozenset(
        {
            StepState.RUNNING,
            StepState.PENDING,
            StepState.SUCCEEDED,
            StepState.FAILED,
            StepState.OUTCOME_UNKNOWN,
        }
    ),
    StepState.OUTCOME_UNKNOWN: frozenset(
        {
            StepState.PENDING,
            StepState.SUCCEEDED,
            StepState.FAILED,
        }
    ),
    StepState.SUCCEEDED: frozenset(),
    StepState.SKIPPED: frozenset(),
    StepState.FAILED: frozenset(),
}


def execution_is_terminal(status: ExecutionStatus) -> bool:
    """Whether the execution can never change again."""
    return status in TERMINAL_EXECUTION_STATES


def step_is_terminal(state: StepState) -> bool:
    """Whether the step has resolved for this execution."""
    return state in TERMINAL_STEP_STATES


def execution_transition_allowed(current: ExecutionStatus, target: ExecutionStatus) -> bool:
    """Whether ``current -> target`` is one of the legal execution transitions."""
    return target in EXECUTION_TRANSITIONS[current]


def step_transition_allowed(current: StepState, target: StepState) -> bool:
    """Whether ``current -> target`` is one of the legal step transitions."""
    return target in STEP_TRANSITIONS[current]


def require_execution_transition(current: ExecutionStatus, target: ExecutionStatus) -> None:
    """Raise :class:`DurableStateError` unless ``current -> target`` is legal."""
    if not execution_transition_allowed(current, target):
        raise DurableStateError(
            f"an execution cannot move from {current.value!r} to {target.value!r}"
        )


def require_step_transition(current: StepState, target: StepState) -> None:
    """Raise :class:`DurableStateError` unless ``current -> target`` is legal."""
    if not step_transition_allowed(current, target):
        raise DurableStateError(f"a step cannot move from {current.value!r} to {target.value!r}")


@dataclass(frozen=True)
class ActivityPolicy:
    """What the executor may do when an interrupted attempt's outcome cannot be proven.

    A step that declares ``idempotent`` is retried, because running it twice is known to be
    harmless. A step that supplies a ``reconcile`` callable is asked what happened. A step that
    declares neither parks the execution in ``WAITING`` with the step recorded as
    ``OUTCOME_UNKNOWN``, because guessing on the caller's behalf is how a payment gets taken twice.
    """

    idempotent: bool = False
    reconcile: Callable[[str, object], Reconciliation] | None = None

    def __post_init__(self) -> None:
        if self.idempotent and self.reconcile is not None:
            raise DurableStateError(
                "an activity policy takes either idempotent=True or a reconciler, not both: "
                "an idempotent step is retried, a reconciler is asked what happened"
            )
        if self.reconcile is not None and not callable(self.reconcile):
            raise DurableStateError("reconcile must be callable")


@dataclass(frozen=True)
class Reconciliation:
    """What a reconciler decided about an interrupted attempt.

    A reconciler is the only thing allowed to say "the effect happened" after a crash, so it returns
    one of three answers: the step succeeded (with the output the effect produced), the step never
    happened and may be run again, or the step definitely failed.
    """

    state: StepState
    output: object = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.state not in (
            StepState.SUCCEEDED,
            StepState.PENDING,
            StepState.FAILED,
            StepState.OUTCOME_UNKNOWN,
        ):
            raise DurableStateError(
                f"a reconciler cannot decide {self.state.value!r}; it reports succeeded, pending, "
                "failed, or outcome_unknown"
            )


@dataclass(frozen=True)
class ExecutionHandle:
    """A submitted execution, as returned to the caller."""

    execution_id: str
    workflow: str
    version: str
    status: ExecutionStatus


@dataclass(frozen=True)
class Claim:
    """A worker's authority to advance one execution.

    ``fence`` is the fencing token: every write the worker makes carries it, so a worker whose lease
    expired loses the ability to commit even while it keeps running.
    """

    execution_id: str
    owner: str
    fence: int
    workflow: str
    version: str
    fingerprint: str
    input: object
    execution_status: ExecutionStatus
    expires_at: datetime
    deadline_at: datetime | None = None
    cancellation_requested: bool = False


@dataclass(frozen=True)
class StepView:
    """One step's persisted state, for inspection."""

    step_id: str
    state: StepState
    attempts: int
    output: object = None
    error_type: str | None = None
    error_message: str | None = None
    state_detail: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class EventView:
    """One journal event, for inspection."""

    sequence: int
    kind: EventKind
    at: datetime
    step_id: str | None = None
    attempt: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ExecutionView:
    """A read-only view of one execution: what it is, where it got to, and why it stopped."""

    execution_id: str
    workflow: str
    version: str
    fingerprint: str
    status: ExecutionStatus
    input: object
    submitted_at: datetime
    updated_at: datetime
    deadline_at: datetime | None = None
    current_step: str | None = None
    result: object = None
    failure_kind: FailureKind | None = None
    failure_message: str | None = None
    cancellation_requested_at: datetime | None = None
    steps: tuple[StepView, ...] = ()
    events: tuple[EventView, ...] = ()
    retry_due_at: datetime | None = None


@dataclass(frozen=True)
class JournalStats:
    """Queue and lease counters for operational diagnostics."""

    queued: int = 0
    running: int = 0
    retrying: int = 0
    waiting: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    timed_out: int = 0
    expired_leases: int = 0
    incompatible: int = 0
    oldest_lease_age_seconds: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
