"""Store behavior: submission, atomic claims, fencing, guarded transitions, and inspection.

Every test runs against a real SQLite journal file, because the guarantees under test are the
database's: an atomic conditional update, a lease with an expiry, and a write that loses its guard.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from xyberos.durable import (
    ActivityPolicy,
    ExecutionStatus,
    FailureKind,
    JournalSettings,
    JournalStore,
    StepState,
    open_journal,
    warn_experimental,
)
from xyberos.durable.testing import ManualWallClock
from xyberos.errors import (
    DurableConflictError,
    DurableError,
    DurableLeaseError,
    DurableOutcomeUnknownError,
    DurablePayloadError,
    DurableStateError,
    DurableVersionError,
    ExperimentalWarning,
    TransientError,
)
from xyberos.execution import Workflow


async def step_one(value: Any, context: Any) -> str:
    return "one"


async def step_two(value: str, context: Any) -> str:
    return f"two:{value}"


def two_step_workflow() -> Workflow:
    return (
        Workflow("support", version="1")
        .step("one", step_one)
        .step("two", step_two)
        .edge("one", "two")
    )


class Harness:
    """A journal, a store, and a virtual clock, torn down together."""

    def __init__(self, tmp_path: Path, **settings: Any) -> None:
        self.settings = JournalSettings(path=tmp_path / "journal.db", **settings)
        self.clock = ManualWallClock()
        self.journal: Any = None
        self.store: JournalStore

    async def __aenter__(self) -> JournalStore:
        self.journal = await open_journal(self.settings)
        self.store = JournalStore(self.journal, clock=self.clock)
        return self.store

    async def __aexit__(self, *_: object) -> None:
        await self.journal.aclose()


def test_submitting_persists_the_execution_and_its_starting_events(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input={"ticket": "T-1"})

            view = await store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.PENDING
            assert view.workflow == "support"
            assert view.version == "1"
            assert view.input == {"ticket": "T-1"}
            assert [step.step_id for step in view.steps] == ["one", "two"]
            assert {step.state for step in view.steps} == {StepState.PENDING}
            assert [event.kind.value for event in view.events] == ["submitted"]

    asyncio.run(scenario())


def test_resubmitting_the_same_execution_is_idempotent(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            workflow = two_step_workflow()
            first = await store.submit(workflow, input={"ticket": "T-1"}, execution_id="exec-1")
            second = await store.submit(workflow, input={"ticket": "T-1"}, execution_id="exec-1")

            assert second == first
            view = await store.inspect("exec-1")
            assert [event.kind.value for event in view.events] == ["submitted"]

    asyncio.run(scenario())


def test_resubmitting_the_same_id_for_different_work_conflicts(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            workflow = two_step_workflow()
            await store.submit(workflow, input={"ticket": "T-1"}, execution_id="exec-1")

            with pytest.raises(DurableConflictError):
                await store.submit(workflow, input={"ticket": "T-2"}, execution_id="exec-1")

    asyncio.run(scenario())


def test_a_definition_cannot_change_under_a_registered_version(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            await store.register_definition(two_step_workflow())

            changed = (
                Workflow("support", version="1")
                .step("one", step_one)
                .step("other", step_two)
                .edge("one", "other")
            )
            with pytest.raises(DurableVersionError) as raised:
                await store.register_definition(changed)

            assert "different definition" in str(raised.value)

    asyncio.run(scenario())


def test_payloads_must_be_serializable_and_bounded(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path, max_payload_bytes=64) as store:
            with pytest.raises(DurablePayloadError) as raised:
                await store.submit(two_step_workflow(), input={"callback": object()})
            assert "not JSON-serializable" in str(raised.value)

            with pytest.raises(DurablePayloadError) as oversized:
                await store.submit(two_step_workflow(), input={"blob": "x" * 100})
            assert "payload limit" in str(oversized.value)

            handle = await store.submit(two_step_workflow(), input={"ticket": "T-1"})
            claim = await store.claim_next("worker-a")
            assert claim is not None
            await store.start_step(claim, "one")
            with pytest.raises(DurablePayloadError):
                await store.complete_step(claim, "one", "y" * 100)
            assert handle.status is ExecutionStatus.PENDING

    asyncio.run(scenario())


def test_claiming_takes_the_oldest_execution_and_only_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            assert await store.claim_next("worker-a") is None

            handle = await store.submit(two_step_workflow(), input={"ticket": "T-1"})
            first = await store.claim_next("worker-a")

            assert first is not None
            assert first.execution_id == handle.execution_id
            assert first.fence == 1
            # The lease is live, so no other worker — and not this one either — can claim it.
            assert await store.claim_next("worker-b") is None

            view = await store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.RUNNING
            assert [event.kind.value for event in view.events] == ["submitted", "claimed"]

    asyncio.run(scenario())


def test_an_expired_lease_is_reclaimed_with_a_higher_fence(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path, lease_ttl_seconds=30.0) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            first = await store.claim_next("worker-a")
            assert first is not None

            store.clock.advance(31.0)
            second = await store.claim_next("worker-b")

            assert second is not None
            assert second.fence == first.fence + 1
            assert second.execution_id == handle.execution_id
            # A crashed worker's execution is claimable again, which is what makes recovery
            # possible without an operator.
            assert second.execution_status is ExecutionStatus.RUNNING
            assert (await store.inspect(handle.execution_id)).status is ExecutionStatus.RUNNING

    asyncio.run(scenario())


def test_a_stale_worker_cannot_commit_anything(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path, lease_ttl_seconds=30.0) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            stale = await store.claim_next("worker-a")
            assert stale is not None
            store.clock.advance(31.0)
            fresh = await store.claim_next("worker-b")
            assert fresh is not None

            with pytest.raises(DurableLeaseError) as raised:
                await store.start_step(stale, "one")
            assert "fence 1" in str(raised.value)
            assert "fence 2" in str(raised.value)

            with pytest.raises(DurableLeaseError):
                await store.complete_execution(stale, {"one": "value"})

            with pytest.raises(DurableLeaseError):
                await store.renew_lease(stale)

            # The fresh owner proceeds normally.
            await store.start_step(fresh, "one")
            await store.complete_step(fresh, "one", "one")
            view = await store.inspect(handle.execution_id)
            assert view.steps[0].state is StepState.SUCCEEDED
            assert view.status is ExecutionStatus.RUNNING

    asyncio.run(scenario())


def test_a_lease_can_be_renewed_but_not_by_a_lost_owner(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path, lease_ttl_seconds=30.0) as store:
            await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None

            store.clock.advance(20.0)
            renewed = await store.renew_lease(claim)
            assert renewed.fence == claim.fence
            assert renewed.expires_at > claim.expires_at

            store.clock.advance(11.0)
            # The renewal bought the worker another lease; the original expiry has passed but the
            # claim is still valid, and renewing again works.
            again = await store.renew_lease(renewed)
            assert again.expires_at > renewed.expires_at

            store.clock.advance(31.0)
            with pytest.raises(DurableLeaseError):
                await store.renew_lease(again)

            view = await store.inspect((await store.list_executions())[0].execution_id)
            assert any(event.kind.value == "lease_renewed" for event in view.events)

    asyncio.run(scenario())


def test_step_attempts_and_results_are_persisted_in_order(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input="start")

            claim = await store.claim_next("worker-a")
            assert claim is not None
            attempt = await store.start_step(claim, "one")
            assert attempt == 1
            await store.complete_step(claim, "one", "one-out")

            recorded = await store.inspect(handle.execution_id)
            # The step is recorded, but the worker still owns the execution until it yields.
            assert recorded.status is ExecutionStatus.RUNNING
            assert recorded.current_step is None
            assert recorded.steps[0].output == "one-out"
            assert await store.step_output(handle.execution_id, "one") == "one-out"
            assert await store.step_states(handle.execution_id) == {
                "one": StepState.SUCCEEDED,
                "two": StepState.PENDING,
            }

            await store.yield_execution(claim)
            assert (await store.inspect(handle.execution_id)).status is ExecutionStatus.PENDING

            second = await store.claim_next("worker-a")
            assert second is not None and second.fence == 2
            await store.start_step(second, "two")
            await store.complete_step(second, "two", "two:one-out")
            await store.yield_execution(second)

            events = (await store.inspect(handle.execution_id)).events
            kinds = [event.kind.value for event in events]
            assert kinds == [
                "submitted",
                "claimed",
                "step_started",
                "step_succeeded",
                "yielded",
                "claimed",
                "step_started",
                "step_succeeded",
                "yielded",
            ]

    asyncio.run(scenario())


def test_a_step_that_already_resolved_cannot_be_transitioned_again(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None
            await store.start_step(claim, "one")
            await store.complete_step(claim, "one", "one-out")

            with pytest.raises(DurableStateError) as raised:
                await store.skip_step(claim, "one", reason="too late")
            assert "cannot move from 'succeeded' to 'skipped'" in str(raised.value)

            with pytest.raises(DurableStateError):
                await store.complete_step(claim, "one", "again")

    asyncio.run(scenario())


def test_skipping_records_a_step_no_branch_reached(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None

            await store.skip_step(claim, "two", reason="no branch reached this step")

            view = await store.inspect(handle.execution_id)
            assert view.steps[1].state is StepState.SKIPPED
            assert view.steps[1].state_detail == "no branch reached this step"
            assert [event.kind.value for event in view.events][-1] == "step_skipped"

    asyncio.run(scenario())


def test_a_retry_is_scheduled_and_waits_for_its_due_time(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None
            await store.start_step(claim, "one")

            due = store.clock.now() + timedelta(seconds=5)
            state = await store.fail_step(
                claim,
                "one",
                error_type="TransientServiceError",
                error_message="try again",
                retry_at=due,
                reason="policy",
            )
            assert state is StepState.PENDING

            retrying = await store.inspect(handle.execution_id)
            assert retrying.status is ExecutionStatus.RETRYING
            assert retrying.retry_due_at == due
            assert retrying.steps[0].attempts == 1
            assert retrying.steps[0].error_type == "TransientServiceError"
            assert [event.kind.value for event in retrying.events][-2:] == [
                "step_failed",
                "retry_scheduled",
            ]

            # Not due yet.
            assert await store.claim_next("worker-a") is None

            store.clock.advance(5.0)
            retry = await store.claim_next("worker-a")
            assert retry is not None
            assert (await store.inspect(handle.execution_id)).retry_due_at is None
            attempt = await store.start_step(retry, "one")
            assert attempt == 2

    asyncio.run(scenario())


def test_a_failed_step_without_a_retry_fails_the_execution(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None
            await store.start_step(claim, "one")

            state = await store.fail_step(
                claim,
                "one",
                error_type="ValueError",
                error_message="bad input",
                retry_at=None,
            )

            assert state is StepState.FAILED
            view = await store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.FAILED
            assert view.failure_kind is FailureKind.STEP_FAILED
            assert view.steps[0].state is StepState.FAILED
            assert view.steps[1].state is StepState.PENDING
            assert [event.kind.value for event in view.events][-2:] == ["step_failed", "failed"]

    asyncio.run(scenario())


def test_a_retry_beyond_the_deadline_times_the_execution_out(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None, timeout=10.0)
            claim = await store.claim_next("worker-a")
            assert claim is not None
            await store.start_step(claim, "one")

            await store.fail_step(
                claim,
                "one",
                error_type="TransientServiceError",
                error_message="try again",
                retry_at=store.clock.now() + timedelta(seconds=30),
            )

            view = await store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.TIMED_OUT
            assert view.failure_kind is FailureKind.TIMED_OUT
            assert view.retry_due_at is None

    asyncio.run(scenario())


def test_the_deadline_is_enforced_before_a_claim_and_by_the_expiry_pass(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None, timeout=10.0)
            store.clock.advance(11.0)

            assert await store.claim_next("worker-a") is None
            assert await store.expire_deadlines() == (handle.execution_id,)
            view = await store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.TIMED_OUT
            assert [event.kind.value for event in view.events][-1] == "timed_out"
            assert await store.expire_deadlines() == ()

    asyncio.run(scenario())


def test_cancelling_an_unowned_execution_finishes_it(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)

            view = await store.request_cancellation(handle.execution_id, reason="operator")

            assert view.status is ExecutionStatus.CANCELLED
            assert view.failure_kind is FailureKind.CANCELLED
            assert view.cancellation_requested_at is not None
            assert [event.kind.value for event in view.events][-2:] == [
                "cancellation_requested",
                "cancelled",
            ]
            assert await store.claim_next("worker-a") is None

    asyncio.run(scenario())


def test_cancellation_wins_over_a_racing_worker(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None
            await store.start_step(claim, "one")
            await store.complete_step(claim, "one", "one-out")

            waiting = await store.request_cancellation(handle.execution_id, reason="operator")
            assert waiting.status is ExecutionStatus.RUNNING
            assert waiting.cancellation_requested_at is not None

            with pytest.raises(DurableStateError) as raised:
                await store.complete_execution(claim, {"two": "value"})
            assert "cancelled" in str(raised.value)

            await store.acknowledge_cancellation(claim, reason="operator")
            view = await store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.CANCELLED
            assert [event.kind.value for event in view.events][-1] == "cancelled"

    asyncio.run(scenario())


def test_a_stale_worker_cannot_acknowledge_a_cancellation(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path, lease_ttl_seconds=30.0) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            stale = await store.claim_next("worker-a")
            assert stale is not None
            store.clock.advance(31.0)
            fresh = await store.claim_next("worker-b")
            assert fresh is not None
            await store.request_cancellation(handle.execution_id, reason="operator")

            with pytest.raises(DurableLeaseError):
                await store.acknowledge_cancellation(stale, reason="operator")

            await store.acknowledge_cancellation(fresh, reason="operator")
            assert (await store.inspect(handle.execution_id)).status is ExecutionStatus.CANCELLED

    asyncio.run(scenario())


def test_an_uncertain_outcome_parks_the_execution(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None
            await store.start_step(claim, "one")

            await store.mark_step_outcome_unknown(claim, "one", reason="crash during the call")

            parked = await store.inspect(handle.execution_id)
            assert parked.status is ExecutionStatus.WAITING
            assert parked.steps[0].state is StepState.OUTCOME_UNKNOWN
            assert parked.steps[0].state_detail == "crash during the call"
            assert [event.kind.value for event in parked.events][-2:] == [
                "step_outcome_unknown",
                "waiting",
            ]
            assert await store.claim_next("worker-a") is None

            resume = await store.claim_next("worker-a")
            assert resume is None  # a parked execution is nobody's to claim by accident

            # An operator (or a reconciler) resolves it, and the execution becomes claimable again.
            await store.resume_waiting(handle.execution_id, reason="operator decided")
            resumed = await store.claim_next("worker-b")
            assert resumed is not None
            await store.resolve_step(resumed, "one", state=StepState.SUCCEEDED, output="reconciled")
            view = await store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.PENDING
            assert view.steps[0].state is StepState.SUCCEEDED
            assert view.steps[0].output == "reconciled"

    asyncio.run(scenario())


def test_only_a_parked_execution_can_be_resumed(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)

            with pytest.raises(DurableStateError) as raised:
                await store.resume_waiting(handle.execution_id)

            assert "not waiting" in str(raised.value)

    asyncio.run(scenario())


def test_completing_records_the_result_and_refuses_a_second_time(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None
            await store.start_step(claim, "one")
            await store.complete_step(claim, "one", "one-out")
            await store.yield_execution(claim)
            second = await store.claim_next("worker-a")
            assert second is not None
            await store.start_step(second, "two")
            await store.complete_step(second, "two", "two-out")

            await store.complete_execution(second, {"two": "two-out"})

            view = await store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.COMPLETED
            assert view.result == {"two": "two-out"}
            assert [event.kind.value for event in view.events][-1] == "completed"

            with pytest.raises(DurableStateError):
                await store.fail_execution(second, kind=FailureKind.INTERNAL, message="too late")

    asyncio.run(scenario())


def test_an_incompatible_definition_is_recorded_as_a_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None

            await store.fail_execution(
                claim,
                kind=FailureKind.INCOMPATIBLE_DEFINITION,
                message="the registered definition does not match the journal fingerprint",
            )

            view = await store.inspect(handle.execution_id)
            assert view.failure_kind is FailureKind.INCOMPATIBLE_DEFINITION
            stats = await store.stats()
            assert stats.incompatible == 1
            assert stats.failed == 1

    asyncio.run(scenario())


def test_a_step_outside_the_definition_is_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None

            with pytest.raises(DurableStateError) as raised:
                await store.start_step(claim, "unknown")

            assert "not part of execution" in str(raised.value)

    asyncio.run(scenario())


def test_inspection_lists_and_counts_work(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            first = await store.submit(two_step_workflow(), input=None, execution_id="exec-1")
            second = await store.submit(two_step_workflow(), input=None, execution_id="exec-2")
            claim = await store.claim_next("worker-a")
            assert claim is not None and claim.execution_id == first.execution_id
            await store.request_cancellation(second.execution_id)

            running = await store.list_executions(status=ExecutionStatus.RUNNING)
            assert [view.execution_id for view in running] == [first.execution_id]
            cancelled = await store.list_executions(status=ExecutionStatus.CANCELLED)
            assert [view.execution_id for view in cancelled] == [second.execution_id]

            stats = await store.stats()
            assert stats.running == 1
            assert stats.cancelled == 1
            assert stats.queued == 0
            assert stats.oldest_lease_age_seconds == 0.0
            assert stats.detail["paths"].endswith("journal.db")
            assert await store.expired_leases() == ()

    asyncio.run(scenario())


def test_expired_leases_are_listed_for_recovery(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path, lease_ttl_seconds=30.0) as store:
            handle = await store.submit(two_step_workflow(), input=None)
            await store.claim_next("worker-a")
            assert await store.expired_leases() == ()

            store.clock.advance(31.0)

            assert await store.expired_leases() == (handle.execution_id,)
            stats = await store.stats()
            assert stats.expired_leases == 1

    asyncio.run(scenario())


def test_a_released_lease_hands_the_work_over_immediately(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path, lease_ttl_seconds=300.0) as store:
            await store.submit(two_step_workflow(), input=None)
            claim = await store.claim_next("worker-a")
            assert claim is not None

            await store.release_lease(claim)

            taken = await store.claim_next("worker-b")
            assert taken is not None
            assert taken.fence == claim.fence + 1

    asyncio.run(scenario())


def test_claiming_requires_an_owner_and_a_positive_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            with pytest.raises(DurableStateError):
                await store.claim_next("  ")
            with pytest.raises(DurableStateError):
                await store.list_executions(limit=0)

    asyncio.run(scenario())


def test_a_timeout_must_be_positive_and_keys_must_not_be_blank(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            with pytest.raises(DurableStateError):
                await store.submit(two_step_workflow(), timeout=0)
            with pytest.raises(DurableStateError):
                await store.submit(two_step_workflow(), submission_key="  ")

    asyncio.run(scenario())


def test_the_activity_policy_lookup_defaults_to_the_safe_choice(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Harness(tmp_path) as store:
            policies = {"one": ActivityPolicy(idempotent=True)}

            assert store.activity_policy(policies, "one").idempotent is True
            default = store.activity_policy(policies, "two")
            assert default.idempotent is False
            assert default.reconcile is None

    asyncio.run(scenario())


def test_the_experimental_warning_names_the_limits() -> None:
    with pytest.warns(ExperimentalWarning) as raised:
        warn_experimental("the durable executor")

    message = str(raised[0].message)
    assert "experimental" in message
    assert "single-host" in message
    assert "at-least-once" in message


def test_an_uncertain_outcome_is_not_retried_by_default() -> None:
    error = DurableOutcomeUnknownError("the effect may already have happened")

    assert not isinstance(error, TransientError)
    assert isinstance(error, DurableError)
