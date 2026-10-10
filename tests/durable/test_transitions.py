"""The transition table is the contract: every row is exercised, and every illegal move raises."""

from __future__ import annotations

import pytest

from xyberos.durable import (
    EXECUTION_TRANSITIONS,
    STEP_TRANSITIONS,
    TERMINAL_EXECUTION_STATES,
    TERMINAL_STEP_STATES,
    ActivityPolicy,
    ExecutionStatus,
    StepState,
    execution_transition_allowed,
    require_execution_transition,
    require_step_transition,
    step_transition_allowed,
)
from xyberos.errors import DurableStateError

# The allowed moves, written out in full. A change to the table has to change this test, which is
# the point: the table is a contract, not an implementation detail.
LEGAL_EXECUTION_TRANSITIONS = {
    ExecutionStatus.PENDING: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.RUNNING: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.PENDING,
        ExecutionStatus.RETRYING,
        ExecutionStatus.WAITING,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    },
    ExecutionStatus.RETRYING: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.WAITING,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    },
    ExecutionStatus.WAITING: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    },
    ExecutionStatus.COMPLETED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.CANCELLED: set(),
    ExecutionStatus.TIMED_OUT: set(),
}

LEGAL_STEP_TRANSITIONS = {
    StepState.PENDING: {
        StepState.RUNNING,
        StepState.SKIPPED,
        StepState.FAILED,
        StepState.OUTCOME_UNKNOWN,
    },
    StepState.RUNNING: {
        StepState.RUNNING,
        StepState.PENDING,
        StepState.SUCCEEDED,
        StepState.FAILED,
        StepState.OUTCOME_UNKNOWN,
    },
    StepState.OUTCOME_UNKNOWN: {StepState.PENDING, StepState.SUCCEEDED, StepState.FAILED},
    StepState.SUCCEEDED: set(),
    StepState.SKIPPED: set(),
    StepState.FAILED: set(),
}


def test_every_execution_state_has_a_row() -> None:
    assert set(EXECUTION_TRANSITIONS) == set(ExecutionStatus)


def test_every_step_state_has_a_row() -> None:
    assert set(STEP_TRANSITIONS) == set(StepState)


def test_execution_transitions_match_the_contract() -> None:
    actual = {state: set(targets) for state, targets in EXECUTION_TRANSITIONS.items()}

    assert actual == LEGAL_EXECUTION_TRANSITIONS


def test_step_transitions_match_the_contract() -> None:
    actual = {state: set(targets) for state, targets in STEP_TRANSITIONS.items()}

    assert actual == LEGAL_STEP_TRANSITIONS


def test_terminal_states_are_exactly_the_states_with_no_way_out() -> None:
    assert {
        state for state in ExecutionStatus if not EXECUTION_TRANSITIONS[state]
    } == TERMINAL_EXECUTION_STATES
    assert {state for state in StepState if not STEP_TRANSITIONS[state]} == TERMINAL_STEP_STATES


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (ExecutionStatus.COMPLETED, ExecutionStatus.RUNNING),
        (ExecutionStatus.FAILED, ExecutionStatus.PENDING),
        (ExecutionStatus.CANCELLED, ExecutionStatus.COMPLETED),
        (ExecutionStatus.TIMED_OUT, ExecutionStatus.RUNNING),
        (ExecutionStatus.PENDING, ExecutionStatus.COMPLETED),
        (ExecutionStatus.RETRYING, ExecutionStatus.COMPLETED),
    ],
)
def test_illegal_execution_transitions_raise(
    source: ExecutionStatus, target: ExecutionStatus
) -> None:
    assert not execution_transition_allowed(source, target)

    with pytest.raises(DurableStateError) as raised:
        require_execution_transition(source, target)

    assert source.value in str(raised.value)
    assert target.value in str(raised.value)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (StepState.SUCCEEDED, StepState.RUNNING),
        (StepState.SKIPPED, StepState.RUNNING),
        (StepState.FAILED, StepState.PENDING),
        (StepState.PENDING, StepState.SUCCEEDED),
    ],
)
def test_illegal_step_transitions_raise(source: StepState, target: StepState) -> None:
    assert not step_transition_allowed(source, target)

    with pytest.raises(DurableStateError):
        require_step_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (ExecutionStatus.PENDING, ExecutionStatus.RUNNING),
        (ExecutionStatus.RUNNING, ExecutionStatus.RETRYING),
        (ExecutionStatus.RUNNING, ExecutionStatus.RUNNING),
        (ExecutionStatus.WAITING, ExecutionStatus.CANCELLED),
    ],
)
def test_legal_execution_transitions_pass(source: ExecutionStatus, target: ExecutionStatus) -> None:
    require_execution_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (StepState.PENDING, StepState.RUNNING),
        (StepState.RUNNING, StepState.PENDING),
        (StepState.RUNNING, StepState.OUTCOME_UNKNOWN),
        (StepState.OUTCOME_UNKNOWN, StepState.SUCCEEDED),
    ],
)
def test_legal_step_transitions_pass(source: StepState, target: StepState) -> None:
    require_step_transition(source, target)


def test_an_activity_policy_takes_idempotency_or_a_reconciler() -> None:
    with pytest.raises(DurableStateError) as raised:
        ActivityPolicy(idempotent=True, reconcile=lambda step_id, value: None)

    assert "not both" in str(raised.value)


def test_an_activity_policy_rejects_a_non_callable_reconciler() -> None:
    with pytest.raises(DurableStateError):
        ActivityPolicy(reconcile="not callable")  # type: ignore[arg-type]


def test_the_default_activity_policy_repeats_nothing() -> None:
    policy = ActivityPolicy()

    assert policy.idempotent is False
    assert policy.reconcile is None
