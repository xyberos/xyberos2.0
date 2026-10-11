"""Worker and recovery behavior, driven one claim at a time on a virtual clock.

These tests are the durable executor's real evidence: a step runs once and is recorded, a retry
waits until it is due, a cancellation is honored before and during a step, and an interrupted
attempt is resolved by policy rather than by guessing.
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
    Reconciliation,
    StepState,
    open_journal,
)
from xyberos.durable.recovery import recover
from xyberos.durable.testing import ManualWallClock
from xyberos.durable.worker import DurableWorker, WorkerSettings
from xyberos.errors import DurableStateError, TransientError, WorkflowCancelledError
from xyberos.execution import Backoff, Retry, Workflow


class Boom(TransientError):
    """A failure a retry policy may retry."""


async def entry(value: object, context: object) -> str:
    return "entry"


async def second(value: str, context: object) -> str:
    return f"second:{value}"


def two_step() -> Workflow:
    return (
        Workflow("support", version="1").step("one", entry).step("two", second).edge("one", "two")
    )


class Rig:
    """A journal, a store, a worker, and a virtual clock that a test controls."""

    def __init__(
        self,
        tmp_path: Path,
        workflow: Workflow | None = None,
        *,
        activities: dict[str, ActivityPolicy] | None = None,
        definitions: dict[str, Workflow] | None = None,
        **settings: Any,
    ) -> None:
        workflow = workflow or two_step()
        self.settings = JournalSettings(path=tmp_path / "journal.db", **settings)
        self.clock = ManualWallClock()
        self.lookup = {f"{workflow.name}:{workflow.version}": workflow}
        if definitions:
            self.lookup.update(definitions)
        self.activities = activities or {}
        self.journal: Any = None
        self.store: JournalStore
        self.worker: DurableWorker

    async def __aenter__(self) -> Rig:
        self.journal = await open_journal(self.settings)
        self.store = JournalStore(self.journal, clock=self.clock)
        self.worker = DurableWorker(
            self.store,
            self.lookup,
            activities=self.activities,
            settings=WorkerSettings(owner="worker-a"),
            clock=self.clock,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.journal.aclose()

    def other_worker(self, owner: str = "worker-b") -> DurableWorker:
        return DurableWorker(
            self.store,
            self.lookup,
            activities=self.activities,
            settings=WorkerSettings(owner=owner),
            clock=self.clock,
        )

    async def await_event(self, execution_id: str, kind: str, *, ticks: int = 200) -> list[Any]:
        """Yield until the journal records ``kind``, and return the events.

        Some events are written by a task behind the step, and how many loop turns the write needs
        is not something a test can assert: two yields are enough on one interpreter and not on the
        next. This waits for the record itself, and fails loudly rather than reporting a surprising
        event list when it never arrives.
        """
        for _ in range(ticks):
            events = (await self.store.inspect(execution_id)).events
            if kind in [event.kind.value for event in events]:
                return events
            await asyncio.sleep(0)
        raise AssertionError(f"the journal never recorded {kind} for {execution_id}")


def test_an_idle_worker_reports_no_work(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path) as rig:
            assert await rig.worker.run_once() is None

    asyncio.run(scenario())


def test_the_worker_runs_one_step_per_claim_and_completes_the_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path) as rig:
            handle = await rig.store.submit(two_step(), input="start")

            first = await rig.worker.run_once()
            assert first is not None
            assert (first.action, first.step_id, first.attempt) == ("ran_step", "one", 1)
            mid = await rig.store.inspect(handle.execution_id)
            assert mid.status is ExecutionStatus.PENDING
            assert mid.steps[0].output == "entry"
            assert mid.steps[0].idempotency_key == f"{handle.execution_id}:one"

            final = await rig.worker.run_once()
            assert final is not None
            assert (final.action, final.step_id) == ("completed", "two")
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.COMPLETED
            assert view.result == {"two": "second:entry"}
            assert [step.state for step in view.steps] == [StepState.SUCCEEDED] * 2
            kinds = [event.kind.value for event in view.events]
            assert kinds == [
                "submitted",
                "claimed",
                "step_started",
                "step_succeeded",
                "yielded",
                "claimed",
                "step_started",
                "step_succeeded",
                "completed",
            ]

    asyncio.run(scenario())


def test_a_branch_that_was_not_taken_is_skipped_and_the_rest_runs(tmp_path: Path) -> None:
    async def yes(value: object, context: object) -> str:
        return "yes"

    def branching() -> Workflow:
        return (
            Workflow("branch", version="1")
            .step("start", entry)
            .step("left", yes)
            .step("right", second)
            .edge("start", "left", when=lambda value: value == "entry-left")
            .edge("start", "right")
        )

    async def scenario() -> None:
        async with Rig(tmp_path, branching()) as rig:
            handle = await rig.store.submit(branching())

            first = await rig.worker.run_once()
            assert first is not None and first.step_id == "start"
            second_run = await rig.worker.run_once()
            assert second_run is not None
            assert (second_run.action, second_run.step_id) == ("completed", "right")

            view = await rig.store.inspect(handle.execution_id)
            states = {step.step_id: step.state for step in view.steps}
            assert states == {
                "start": StepState.SUCCEEDED,
                "left": StepState.SKIPPED,
                "right": StepState.SUCCEEDED,
            }
            assert [event.kind.value for event in view.events].count("step_skipped") == 1
            assert view.result == {"right": "second:entry"}

    asyncio.run(scenario())


def test_a_transient_failure_is_scheduled_and_retried(tmp_path: Path) -> None:
    attempts = {"count": 0}

    async def flaky(value: object, context: Any) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise Boom("try again")
        return "recovered"

    def flaky_workflow() -> Workflow:
        return Workflow("flaky", version="1").step(
            "call", flaky, retry=Retry(max_attempts=2, backoff=Backoff(initial=5.0))
        )

    async def scenario() -> None:
        async with Rig(tmp_path, flaky_workflow()) as rig:
            handle = await rig.store.submit(flaky_workflow())

            first = await rig.worker.run_once()
            assert first is not None and first.action == "retry_scheduled"
            assert first.attempt == 1
            scheduled = await rig.store.inspect(handle.execution_id)
            assert scheduled.status is ExecutionStatus.RETRYING
            assert scheduled.retry_due_at == rig.clock.now() + timedelta(seconds=5)
            assert scheduled.steps[0].state is StepState.PENDING

            # Nothing owns a retrying execution, so the lease is not what is holding it back.
            assert await rig.worker.run_once() is None

            rig.clock.advance(5.0)
            second = await rig.worker.run_once()
            assert second is not None and second.action == "completed"
            assert second.attempt == 2
            view = await rig.store.inspect(handle.execution_id)
            assert view.result == {"call": "recovered"}
            assert view.steps[0].attempts == 2

    asyncio.run(scenario())


def test_a_failure_outside_the_policy_stops_the_run(tmp_path: Path) -> None:
    async def broken(value: object, context: object) -> str:
        raise ValueError("programming error")

    def broken_workflow() -> Workflow:
        return Workflow("broken", version="1").step(
            "call", broken, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.0))
        )

    async def scenario() -> None:
        async with Rig(tmp_path, broken_workflow()) as rig:
            handle = await rig.store.submit(broken_workflow())

            outcome = await rig.worker.run_once()

            assert outcome is not None and outcome.action == "failed"
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.FAILED
            assert view.failure_kind is FailureKind.STEP_FAILED
            assert view.steps[0].error_type == "ValueError"
            assert view.steps[0].error_message == "programming error"

    asyncio.run(scenario())


def test_a_step_timeout_fails_the_run_without_retrying(tmp_path: Path) -> None:
    async def slow(value: object, context: object) -> str:
        await asyncio.sleep(5)
        return "late"

    def slow_workflow() -> Workflow:
        return Workflow("slow", version="1").step(
            "call", slow, timeout=0.02, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.0))
        )

    async def scenario() -> None:
        async with Rig(tmp_path, slow_workflow()) as rig:
            handle = await rig.store.submit(slow_workflow())

            outcome = await rig.worker.run_once()

            assert outcome is not None and outcome.action == "failed"
            view = await rig.store.inspect(handle.execution_id)
            assert view.steps[0].error_type == "StepTimeoutError"
            assert view.steps[0].attempts == 1
            assert view.status is ExecutionStatus.FAILED

    asyncio.run(scenario())


def test_a_missing_or_changed_definition_stops_the_execution(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path) as rig:
            handle = await rig.store.submit(two_step())
            rig.lookup.clear()

            outcome = await rig.worker.run_once()

            assert outcome is not None and outcome.action == "failed"
            view = await rig.store.inspect(handle.execution_id)
            assert view.failure_kind is FailureKind.INCOMPATIBLE_DEFINITION
            assert "does not have registered" in (view.failure_message or "")

            # A definition that exists but no longer matches is reported just as clearly.
            changed = (
                Workflow("support", version="1")
                .step("one", entry)
                .step("renamed", second)
                .edge("one", "renamed")
            )
            rig.lookup[f"{changed.name}:{changed.version}"] = changed
            later = await rig.store.submit(two_step(), input="again", execution_id="exec-2")
            outcome = await rig.worker.run_once()
            assert outcome is not None and outcome.action == "failed"
            after = await rig.store.inspect(later.execution_id)
            assert after.failure_kind is FailureKind.INCOMPATIBLE_DEFINITION
            assert "different definition" in (after.failure_message or "")

    asyncio.run(scenario())


def test_two_taken_branches_stop_the_run_as_a_definition_conflict(tmp_path: Path) -> None:
    async def start(value: object, context: object) -> str:
        return "started"

    async def join(value: object, context: object) -> str:
        return f"joined:{value}"

    def conflicting() -> Workflow:
        return (
            Workflow("conflict", version="1")
            .step("left", start)
            .step("right", start)
            .step("join", join)
            .edge("left", "join")
            .edge("right", "join")
        )

    async def scenario() -> None:
        async with Rig(tmp_path, conflicting()) as rig:
            handle = await rig.store.submit(conflicting())

            first = await rig.worker.run_once()
            second = await rig.worker.run_once()

            assert first is not None and first.action == "ran_step"
            # The conflict is detected as soon as both sources have resolved.
            assert second is not None and second.action == "failed"
            view = await rig.store.inspect(handle.execution_id)
            assert view.failure_kind is FailureKind.DEFINITION_CONFLICT
            assert "more than one branch" in (view.failure_message or "")

    asyncio.run(scenario())


def test_a_heartbeat_keeps_a_long_step_owned(tmp_path: Path) -> None:
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow(value: object, context: object) -> str:
        started.set()
        await release.wait()
        return "finished"

    def slow_workflow() -> Workflow:
        return Workflow("slow", version="1").step("call", slow)

    async def scenario() -> None:
        async with Rig(tmp_path, slow_workflow(), lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(slow_workflow())
            task = asyncio.ensure_future(rig.worker.run_once())
            await started.wait()
            await rig.clock.wait_for_sleepers(1)

            # The heartbeat fires well before the lease would expire, and renews it.
            rig.clock.advance(10.0)
            events = await rig.await_event(handle.execution_id, "lease_renewed")
            assert "lease_renewed" in [event.kind.value for event in events]
            assert await rig.store.claim_next("worker-b") is None

            release.set()
            outcome = await task
            assert outcome is not None and outcome.action == "completed"

    asyncio.run(scenario())


def test_cancellation_is_honored_while_a_step_runs(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def cooperative(value: object, context: Any) -> str:
        started.set()
        await context.cancellation.wait()
        context.check()
        return "should not get here"  # pragma: no cover - check() raises first

    def cooperative_workflow() -> Workflow:
        return Workflow("cooperative", version="1").step("call", cooperative)

    async def scenario() -> None:
        async with Rig(tmp_path, cooperative_workflow(), lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(cooperative_workflow())
            task = asyncio.ensure_future(rig.worker.run_once())
            await started.wait()
            await rig.clock.wait_for_sleepers(1)

            await rig.store.request_cancellation(handle.execution_id, reason="operator")
            rig.clock.advance(10.0)
            outcome = await task

            assert outcome is not None and outcome.action == "cancelled"
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.CANCELLED
            assert view.failure_kind is FailureKind.CANCELLED
            kinds = [event.kind.value for event in view.events]
            assert "cancellation_requested" in kinds
            assert kinds[-1] == "cancelled"

    asyncio.run(scenario())


def test_a_cancellation_requested_before_a_step_stops_it_from_running(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path, lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(two_step())
            # A worker dies holding the lease, and a cancellation arrives afterwards. Nothing owns
            # the execution by then, so the request is recorded as final and no step ever starts.
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            rig.clock.advance(31.0)
            await rig.store.request_cancellation(handle.execution_id, reason="operator")

            assert await rig.worker.run_once() is None
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.CANCELLED
            assert view.failure_kind is FailureKind.CANCELLED
            assert view.steps[0].state is StepState.PENDING
            assert view.steps[0].attempts == 0

    asyncio.run(scenario())


def test_serving_runs_recovery_first_and_stops_after_the_cap(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path) as rig:
            await rig.store.submit(two_step())
            await rig.store.submit(two_step(), execution_id="exec-2")

            served = await rig.worker.serve(max_iterations=1)

            assert served == 1
            stats = await rig.store.stats()
            # One execution advanced a step and yielded; both are still queued.
            assert stats.queued == 2
            assert stats.completed == 0

    asyncio.run(scenario())


def test_recovery_resumes_an_execution_that_stopped_between_steps(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path, lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(two_step())
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            rig.clock.advance(31.0)

            report = await rig.worker.recover()

            assert report.expired == (handle.execution_id,)
            assert report.resumed == (handle.execution_id,)
            assert report.decisions[handle.execution_id] == "resolved pending"
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.PENDING
            yielded = [event for event in view.events if event.kind.value == "yielded"]
            assert "recovered after an expired lease" in (yielded[-1].detail or "")

            assert (await rig.worker.run_once()) is not None
            assert (await rig.worker.run_once()) is not None

    asyncio.run(scenario())


def test_an_interrupted_attempt_without_a_policy_is_parked_as_unknown(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path, lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(two_step())
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            await rig.store.start_step(dead, "one")
            rig.clock.advance(31.0)

            report = await rig.worker.recover()

            assert report.parked == (handle.execution_id,)
            assert report.decisions[handle.execution_id] == "outcome_unknown"
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.WAITING
            assert view.steps[0].state is StepState.OUTCOME_UNKNOWN
            assert "declares neither idempotency" in (view.steps[0].state_detail or "")
            assert await rig.worker.run_once() is None

    asyncio.run(scenario())


def test_an_idempotent_activity_is_retried_after_a_crash(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(
            tmp_path,
            activities={"one": ActivityPolicy(idempotent=True)},
            lease_ttl_seconds=30.0,
        ) as rig:
            handle = await rig.store.submit(two_step())
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            await rig.store.start_step(dead, "one")
            rig.clock.advance(31.0)

            report = await rig.worker.recover()
            assert report.resumed == (handle.execution_id,)
            assert report.decisions[handle.execution_id] == "resolved pending"

            outcome = await rig.worker.run_once()
            assert outcome is not None and outcome.step_id == "one"
            assert outcome.attempt == 2
            view = await rig.store.inspect(handle.execution_id)
            assert view.steps[0].state is StepState.SUCCEEDED

    asyncio.run(scenario())


def test_a_reconciler_decides_what_happened(tmp_path: Path) -> None:
    calls: list[str] = []

    def reconcile(step_id: str, step_input: object) -> Reconciliation:
        calls.append(step_id)
        return Reconciliation(
            state=StepState.SUCCEEDED, output="proven", detail="found the receipt"
        )

    async def scenario() -> None:
        async with Rig(
            tmp_path,
            activities={"one": ActivityPolicy(reconcile=reconcile)},
            lease_ttl_seconds=30.0,
        ) as rig:
            handle = await rig.store.submit(two_step(), input="start")
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            await rig.store.start_step(dead, "one")
            rig.clock.advance(31.0)

            report = await rig.worker.recover()

            assert calls == ["one"]
            assert report.resumed == (handle.execution_id,)
            view = await rig.store.inspect(handle.execution_id)
            assert view.steps[0].state is StepState.SUCCEEDED
            assert view.steps[0].output == "proven"
            assert view.steps[0].state_detail == "found the receipt"
            assert view.status is ExecutionStatus.PENDING

            final = await rig.worker.run_once()
            assert final is not None and final.action == "completed"

    asyncio.run(scenario())


def test_a_reconciler_that_cannot_decide_parks_the_execution(tmp_path: Path) -> None:
    def reconcile(step_id: str, step_input: object) -> Reconciliation:
        return Reconciliation(state=StepState.OUTCOME_UNKNOWN, detail="the provider is unreachable")

    async def scenario() -> None:
        async with Rig(
            tmp_path,
            activities={"one": ActivityPolicy(reconcile=reconcile)},
            lease_ttl_seconds=30.0,
        ) as rig:
            handle = await rig.store.submit(two_step())
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            await rig.store.start_step(dead, "one")
            rig.clock.advance(31.0)

            report = await rig.worker.recover()

            assert report.parked == (handle.execution_id,)
            view = await rig.store.inspect(handle.execution_id)
            assert view.steps[0].state_detail == "the provider is unreachable"

    asyncio.run(scenario())


def test_recovery_stops_an_execution_whose_definition_is_gone(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path, lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(two_step())
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            await rig.store.start_step(dead, "one")
            rig.lookup.clear()
            rig.clock.advance(31.0)

            report = await rig.worker.recover()

            assert report.stopped == (handle.execution_id,)
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.FAILED
            assert view.failure_kind is FailureKind.INCOMPATIBLE_DEFINITION

    asyncio.run(scenario())


def test_recovery_records_a_cancellation_that_arrived_too_late(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path, lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(two_step())
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            await rig.store.start_step(dead, "one")
            await rig.store.request_cancellation(handle.execution_id, reason="operator")
            rig.clock.advance(31.0)

            report = await rig.worker.recover()

            assert report.stopped == (handle.execution_id,)
            assert report.decisions[handle.execution_id] == "cancelled"
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.CANCELLED

    asyncio.run(scenario())


def test_recovery_leaves_another_workers_live_work_alone(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path, lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(two_step())
            live = await rig.store.claim_next("healthy-worker")
            assert live is not None

            report = await recover(
                rig.store,
                definitions=rig.lookup,
                owner="recovery",
            )

            assert report.expired == ()
            assert report.examined == 0
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.RUNNING

    asyncio.run(scenario())


def test_a_dead_workers_step_is_not_duplicated_by_a_healthier_worker(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path, lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(two_step())
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            await rig.store.start_step(dead, "one")
            rig.clock.advance(5.0)

            # The lease is still live, so nobody else may take the execution.
            assert await rig.worker.run_once() is None

            rig.clock.advance(26.0)
            parked = await rig.worker.run_once()
            assert parked is not None and parked.action == "parked"
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.WAITING
            # One attempt was recorded, and it was not silently repeated.
            assert view.steps[0].attempts == 1

    asyncio.run(scenario())


def test_worker_settings_and_recovery_outputs_are_validated(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with Rig(tmp_path) as rig:
            with pytest.raises(DurableStateError):
                WorkerSettings(poll_interval=0)
            with pytest.raises(DurableStateError):
                WorkerSettings(owner="   ")
            with pytest.raises(DurableStateError):
                WorkerSettings(heartbeat_seconds=-1)

            handle = await rig.store.submit(two_step())
            claim = await rig.store.claim_next("worker-a")
            assert claim is not None
            await rig.store.start_step(claim, "one")
            view = await rig.store.inspect(handle.execution_id)
            assert view.current_step == "one"

    asyncio.run(scenario())


def test_the_idempotency_key_is_stable_across_attempts(tmp_path: Path) -> None:
    attempts: list[str] = []

    async def flaky(value: object, context: Any) -> str:
        attempts.append(context.step)
        if len(attempts) == 1:
            raise Boom("again")
        return "ok"

    def flaky_workflow() -> Workflow:
        return Workflow("flaky", version="1").step(
            "call", flaky, retry=Retry(max_attempts=2, backoff=Backoff(initial=1.0))
        )

    async def scenario() -> None:
        async with Rig(tmp_path, flaky_workflow()) as rig:
            handle = await rig.store.submit(flaky_workflow())
            await rig.worker.run_once()
            rig.clock.advance(1.0)
            await rig.worker.run_once()

            view = await rig.store.inspect(handle.execution_id)
            assert view.steps[0].idempotency_key == f"{handle.execution_id}:call"
            assert view.steps[0].attempts == 2

    asyncio.run(scenario())


def test_a_parked_execution_is_not_re_run_when_it_is_woken_up(tmp_path: Path) -> None:
    """Resuming a parked execution must not silently repeat an effect of unknown status.

    This is the dangerous window: an operator resumes an execution whose step is ``OUTCOME_UNKNOWN``
    before reconciling it. The worker must park it again with a reason, never run the step.
    """
    attempts: list[str] = []

    async def charge(value: object, context: Any) -> str:
        attempts.append("charge")
        return "charged"

    def charge_workflow() -> Workflow:
        return Workflow("charge", version="1").step("charge", charge)

    async def scenario() -> None:
        async with Rig(tmp_path, charge_workflow(), lease_ttl_seconds=30.0) as rig:
            handle = await rig.store.submit(charge_workflow())
            dead = await rig.store.claim_next("dead-worker")
            assert dead is not None
            await rig.store.start_step(dead, "charge")
            attempts.append("charge")  # the effect happened before the crash
            rig.clock.advance(31.0)
            assert (await rig.worker.recover()).parked == (handle.execution_id,)

            await rig.store.resume_waiting(handle.execution_id, reason="operator woke it up")
            outcome = await rig.worker.run_once()

            assert outcome is not None and outcome.action == "parked"
            assert outcome.detail == "needs_decision"
            # The only recorded attempt is the one the dead worker made before it crashed.
            assert attempts == ["charge"]
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.WAITING
            assert view.steps[0].state is StepState.OUTCOME_UNKNOWN
            assert view.steps[0].attempts == 1

            # Once an operator resolves it, the run continues normally. Resolving needs a claim, and
            # a parked execution has none, so the operator resumes it and then records the decision.
            await rig.store.resume_waiting(handle.execution_id, reason="operator decided")
            claim = await rig.store.claim_next("operator-session")
            assert claim is not None
            await rig.store.resolve_step(
                claim, "charge", state=StepState.SUCCEEDED, output="charged"
            )
            final = await rig.worker.run_once()
            assert final is not None and final.action == "completed"
            # Resolving is not re-running: the effect happened once, in the dead worker's attempt.
            assert attempts == ["charge"]

    asyncio.run(scenario())


def test_a_step_that_stops_the_run_is_honored(tmp_path: Path) -> None:
    async def stop(value: object, context: object) -> str:
        raise WorkflowCancelledError("the operator stopped this run")

    def stopping() -> Workflow:
        return Workflow("stopping", version="1").step("call", stop)

    async def scenario() -> None:
        async with Rig(tmp_path, stopping()) as rig:
            handle = await rig.store.submit(stopping())

            outcome = await rig.worker.run_once()

            assert outcome is not None and outcome.action == "cancelled"
            view = await rig.store.inspect(handle.execution_id)
            assert view.status is ExecutionStatus.CANCELLED

    asyncio.run(scenario())
