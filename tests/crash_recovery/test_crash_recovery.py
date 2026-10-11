"""Process-kill harness: a real child process dies, and the journal decides what happens next.

Each test starts ``child.py`` with the interpreter, so the crash is a genuine process exit — no
``finally`` blocks, no cleanup, no atexit — and then opens the same journal from the parent to prove
what survived and what recovery decides. That is the only way to test the failure table in
``PLAN.md`` section 5.3 honestly: an in-process exception would still leave the worker's own
cleanup running.

The child is a *separate* process, so it cannot share the parent's virtual clock. Tests that need
the dead worker's lease to have run out call :func:`~xyberos.durable.testing.expire_leases`, which
backdates the lease row. That is a virtual clock across a process boundary: identical in effect to
time passing with nobody heartbeating, and deterministic instead of timing-dependent.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from crash_recovery import definition
from crash_recovery.definition import (
    CHARGE,
    RECEIPT,
    count_effects,
    crash_workflow,
    incompatible_workflow,
)
from xyberos.durable import (
    ActivityPolicy,
    ExecutionStatus,
    FailureKind,
    Journal,
    JournalSettings,
    JournalStore,
    Reconciliation,
    StepState,
    open_journal,
)
from xyberos.durable.testing import expire_leases
from xyberos.durable.worker import DurableWorker, WorkerSettings, WorkOutcome

HERE = Path(__file__).resolve().parent
CHILD = HERE / "child.py"
EXECUTION_ID = "crash-demo-execution"

EXIT_CODES = {
    "before-step": 70,
    "during-activity": 71,
    "after-result": 72,
    "before-final": 73,
    "during-lease-renewal": 74,
}


def crash_at(boundary: str, journal_path: Path) -> None:
    """Run the child until it dies at ``boundary``, and assert it died where it was told to."""
    result = subprocess.run(
        [sys.executable, str(CHILD), boundary, str(journal_path)],
        capture_output=True,
        text=True,
        cwd=HERE,
        check=False,
    )

    assert result.returncode == EXIT_CODES[boundary], (
        f"the child did not die at {boundary!r}: exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert f"EXECUTION {EXECUTION_ID}" in result.stdout, result.stdout
    assert f"REACHED {boundary}" in result.stdout, result.stdout


async def open_parent(
    journal_path: Path,
    *,
    workflows: dict[str, Any] | None = None,
    activities: dict[str, ActivityPolicy] | None = None,
) -> tuple[Journal, JournalStore, DurableWorker]:
    """Open the journal the child left behind, as a fresh process would."""
    journal = await open_journal(JournalSettings(path=journal_path, lease_ttl_seconds=30.0))
    store = JournalStore(journal)
    worker = DurableWorker(
        store,
        workflows or {"crash-demo:1": crash_workflow()},
        activities=activities or {},
        settings=WorkerSettings(owner="recovering-worker"),
    )
    return journal, store, worker


async def drain(worker: DurableWorker, *, limit: int = 10) -> list[WorkOutcome]:
    """Advance a worker until it has nothing left to claim."""
    outcomes: list[WorkOutcome] = []
    for _ in range(limit):
        outcome = await worker.run_once()
        if outcome is None:
            return outcomes
        outcomes.append(outcome)
    raise AssertionError(f"the worker still had work after {limit} claims: {outcomes}")


def run_scenario(scenario: Any) -> None:
    asyncio.run(scenario())


def test_the_child_dies_before_the_step_starts_and_the_step_is_rerun(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("before-step", journal_path)

    # Nothing ran, and the work is still there.
    assert count_effects(journal_path, CHARGE) == 0

    async def scenario() -> None:
        journal, store, worker = await open_parent(journal_path)
        try:
            view = await store.inspect(EXECUTION_ID)
            assert view.status is ExecutionStatus.RUNNING
            assert view.steps[0].state is StepState.PENDING
            assert view.steps[0].attempts == 0

            # The lease is still live, so the dead worker's claim is respected, not trampled.
            assert await worker.run_once() is None
            assert await expire_leases(journal) == 1

            report = await worker.recover()
            assert report.resumed == (EXECUTION_ID,)
            assert report.decisions[EXECUTION_ID] == "resolved pending"

            outcomes = await drain(worker)
            assert [outcome.action for outcome in outcomes] == ["ran_step", "completed"]
            final = await store.inspect(EXECUTION_ID)
            assert final.status is ExecutionStatus.COMPLETED
            assert final.steps[0].attempts == 1
            assert final.result == {RECEIPT: "receipt for charged"}
        finally:
            await journal.aclose()

    run_scenario(scenario)
    assert count_effects(journal_path, CHARGE) == 1
    assert count_effects(journal_path, RECEIPT) == 1


def test_a_dead_process_live_lease_blocks_a_second_worker_until_it_expires(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("before-step", journal_path)

    async def scenario() -> None:
        journal, store, worker = await open_parent(journal_path)
        try:
            assert await store.claim_next("other-worker") is None
            assert await store.expired_leases() == ()

            assert await expire_leases(journal) == 1

            assert await store.expired_leases() == (EXECUTION_ID,)
            claim = await store.claim_next("other-worker")
            assert claim is not None
            # A new owner always gets a strictly higher token, so the dead worker can never commit.
            assert claim.fence == 2
            assert claim.owner == "other-worker"
        finally:
            await journal.aclose()

    run_scenario(scenario)
    # Recovery alone must not have repeated anything.
    assert count_effects(journal_path, CHARGE) == 0


def test_a_crash_during_an_activity_is_parked_when_the_step_declares_nothing(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("during-activity", journal_path)
    # The effect happened; only the journal cannot prove it happened exactly once.
    assert count_effects(journal_path, CHARGE) == 1

    async def scenario() -> None:
        journal, store, worker = await open_parent(journal_path)
        try:
            assert await expire_leases(journal) == 1

            report = await worker.recover()

            assert report.parked == (EXECUTION_ID,)
            assert report.resumed == ()
            assert report.decisions[EXECUTION_ID] == "outcome_unknown"
            view = await store.inspect(EXECUTION_ID)
            assert view.status is ExecutionStatus.WAITING
            assert view.steps[0].state is StepState.OUTCOME_UNKNOWN
            assert "declares neither idempotency" in (view.steps[0].state_detail or "")
            # A parked execution is nobody's to claim by accident, and the worker agrees.
            assert await worker.run_once() is None
        finally:
            await journal.aclose()

    run_scenario(scenario)
    # The uncertain attempt was not repeated: that is the whole point of parking it.
    assert count_effects(journal_path, CHARGE) == 1


def test_a_crash_during_an_activity_is_retried_when_the_step_is_idempotent(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("during-activity", journal_path)

    async def scenario() -> None:
        journal, store, worker = await open_parent(
            journal_path, activities={CHARGE: ActivityPolicy(idempotent=True)}
        )
        try:
            assert await expire_leases(journal) == 1

            report = await worker.recover()

            assert report.resumed == (EXECUTION_ID,)
            assert report.decisions[EXECUTION_ID] == "resolved pending"
            outcomes = await drain(worker)
            assert [outcome.action for outcome in outcomes] == ["ran_step", "completed"]
            view = await store.inspect(EXECUTION_ID)
            assert view.status is ExecutionStatus.COMPLETED
            assert view.steps[0].attempts == 2
        finally:
            await journal.aclose()

    run_scenario(scenario)
    # At-least-once, by explicit declaration: the effect happened twice and the run succeeded.
    assert count_effects(journal_path, CHARGE) == 2
    assert count_effects(journal_path, RECEIPT) == 1


def test_a_crash_during_an_activity_is_reconciled_instead_of_repeated(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("during-activity", journal_path)
    seen: list[tuple[str, object]] = []

    def reconcile(step_id: str, step_input: object) -> Reconciliation:
        seen.append((step_id, step_input))
        return Reconciliation(
            state=StepState.SUCCEEDED,
            output={definition.JOURNAL_KEY: str(journal_path), "status": "charged"},
            detail="the provider receipt proves the charge went through",
        )

    async def scenario() -> None:
        journal, store, worker = await open_parent(
            journal_path, activities={CHARGE: ActivityPolicy(reconcile=reconcile)}
        )
        try:
            assert await expire_leases(journal) == 1

            report = await worker.recover()

            assert seen == [(CHARGE, {definition.JOURNAL_KEY: str(journal_path)})]
            assert report.resumed == (EXECUTION_ID,)
            assert report.decisions[EXECUTION_ID] == "resolved succeeded"
            view = await store.inspect(EXECUTION_ID)
            assert view.steps[0].state is StepState.SUCCEEDED
            assert view.steps[0].state_detail == (
                "the provider receipt proves the charge went through"
            )
            assert view.status is ExecutionStatus.PENDING

            outcomes = await drain(worker)
            assert [outcome.action for outcome in outcomes] == ["completed"]
        finally:
            await journal.aclose()

    run_scenario(scenario)
    assert count_effects(journal_path, CHARGE) == 1
    assert count_effects(journal_path, RECEIPT) == 1


def test_a_crash_after_a_result_reuses_the_recorded_result(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("after-result", journal_path)

    async def scenario() -> None:
        journal, store, worker = await open_parent(journal_path)
        try:
            # A committed step result survives a process that never cleaned up after itself.
            view = await store.inspect(EXECUTION_ID)
            assert view.steps[0].state is StepState.SUCCEEDED
            assert view.steps[0].output == {
                definition.JOURNAL_KEY: str(journal_path),
                "status": "charged",
            }
            assert await store.step_output(EXECUTION_ID, CHARGE) == {
                definition.JOURNAL_KEY: str(journal_path),
                "status": "charged",
            }

            assert await expire_leases(journal) == 1
            report = await worker.recover()
            assert report.resumed == (EXECUTION_ID,)

            outcomes = await drain(worker)
            assert [outcome.step_id for outcome in outcomes] == [RECEIPT]
            final = await store.inspect(EXECUTION_ID)
            assert final.status is ExecutionStatus.COMPLETED
            assert final.steps[0].attempts == 1
        finally:
            await journal.aclose()

    run_scenario(scenario)
    # The recorded result was reused: the charge was not taken again.
    assert count_effects(journal_path, CHARGE) == 1
    assert count_effects(journal_path, RECEIPT) == 1


def test_a_crash_before_the_final_transition_does_not_repeat_the_last_step(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("before-final", journal_path)
    assert count_effects(journal_path, RECEIPT) == 1

    async def scenario() -> None:
        journal, store, worker = await open_parent(journal_path)
        try:
            both_done = await store.inspect(EXECUTION_ID)
            assert [step.state for step in both_done.steps] == [
                StepState.SUCCEEDED,
                StepState.SUCCEEDED,
            ]
            assert both_done.status is ExecutionStatus.RUNNING
            assert both_done.result is None

            assert await expire_leases(journal) == 1
            assert (await worker.recover()).resumed == (EXECUTION_ID,)

            outcomes = await drain(worker)
            assert [outcome.action for outcome in outcomes] == ["completed"]
            final = await store.inspect(EXECUTION_ID)
            assert final.result == {RECEIPT: "receipt for charged"}
            assert [step.attempts for step in final.steps] == [1, 1]
        finally:
            await journal.aclose()

    run_scenario(scenario)
    assert count_effects(journal_path, CHARGE) == 1
    assert count_effects(journal_path, RECEIPT) == 1


def test_a_crash_during_lease_renewal_still_respects_the_live_lease_then_recovers(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("during-lease-renewal", journal_path)

    async def scenario() -> None:
        journal, store, worker = await open_parent(
            journal_path, activities={CHARGE: ActivityPolicy(idempotent=True)}
        )
        try:
            # The heartbeat renewed the lease, so the execution is still owned by a process that is
            # already gone — the case fencing exists for.
            assert await store.expired_leases() == ()
            assert await store.claim_next("other-worker") is None
            events = (await store.inspect(EXECUTION_ID)).events
            assert "lease_renewed" in [event.kind.value for event in events]

            assert await expire_leases(journal) == 1
            assert (await worker.recover()).resumed == (EXECUTION_ID,)

            await drain(worker)
            final = await store.inspect(EXECUTION_ID)
            assert final.status is ExecutionStatus.COMPLETED
            assert final.steps[0].attempts == 2
        finally:
            await journal.aclose()

    run_scenario(scenario)
    assert count_effects(journal_path, CHARGE) == 2


def test_a_crash_then_an_incompatible_definition_stops_the_execution_safely(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("during-activity", journal_path)

    async def scenario() -> None:
        journal, store, worker = await open_parent(
            journal_path, workflows={"crash-demo:1": incompatible_workflow()}
        )
        try:
            assert await expire_leases(journal) == 1

            report = await worker.recover()

            assert report.stopped == (EXECUTION_ID,)
            assert report.decisions[EXECUTION_ID] == "incompatible definition"
            view = await store.inspect(EXECUTION_ID)
            assert view.status is ExecutionStatus.FAILED
            assert view.failure_kind is FailureKind.INCOMPATIBLE_DEFINITION
            assert "different definition" in (view.failure_message or "")
            assert await worker.run_once() is None
        finally:
            await journal.aclose()

    run_scenario(scenario)
    # Refusing to guess is also refusing to act: nothing was run against the wrong definition.
    assert count_effects(journal_path, CHARGE) == 1


def test_a_crash_then_an_incompatible_definition_is_refused_by_the_worker_too(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("before-step", journal_path)

    async def scenario() -> None:
        journal, store, worker = await open_parent(
            journal_path, workflows={"crash-demo:1": incompatible_workflow()}
        )
        try:
            assert await expire_leases(journal) == 1

            outcome = await worker.run_once()

            assert outcome is not None and outcome.action == "failed"
            assert outcome.detail == "incompatible definition"
            assert (await store.inspect(EXECUTION_ID)).failure_kind is (
                FailureKind.INCOMPATIBLE_DEFINITION
            )
        finally:
            await journal.aclose()

    run_scenario(scenario)
    assert count_effects(journal_path, CHARGE) == 0


def test_a_crash_then_a_cancellation_request_is_recorded_as_final(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("before-step", journal_path)

    async def scenario() -> None:
        journal, store, worker = await open_parent(journal_path)
        try:
            assert await expire_leases(journal) == 1

            view = await store.request_cancellation(EXECUTION_ID, reason="the operator gave up")

            assert view.status is ExecutionStatus.CANCELLED
            assert view.failure_kind is FailureKind.CANCELLED
            kinds = [event.kind.value for event in view.events]
            assert kinds[-2:] == ["cancellation_requested", "cancelled"]
            assert await worker.run_once() is None
        finally:
            await journal.aclose()

    run_scenario(scenario)
    assert count_effects(journal_path, CHARGE) == 0


def test_a_crash_never_leaves_an_orphan_claim_that_cannot_be_taken_over(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.db"
    crash_at("during-lease-renewal", journal_path)

    async def scenario() -> None:
        journal, store, worker = await open_parent(
            journal_path, activities={CHARGE: ActivityPolicy(idempotent=True)}
        )
        try:
            stats = await store.stats()
            assert stats.running == 1
            assert stats.expired_leases == 0

            assert await expire_leases(journal) == 1

            assert (await store.stats()).expired_leases == 1
            await worker.recover()
            assert (await store.stats()).expired_leases == 0
            await drain(worker)
            assert (await store.stats()).completed == 1
        finally:
            await journal.aclose()

    run_scenario(scenario)


@pytest.mark.parametrize("boundary", sorted(EXIT_CODES))
def test_every_documented_boundary_is_reachable(tmp_path: Path, boundary: str) -> None:
    # A guard against a harness that silently stops crashing where it says it does: if a boundary
    # ever became unreachable, the tests above would pass for the wrong reason.
    journal_path = tmp_path / "journal.db"

    crash_at(boundary, journal_path)

    assert journal_path.exists()
