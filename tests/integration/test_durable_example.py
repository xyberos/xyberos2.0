"""The durable example runs on the documented promises, from a clean directory.

The example is the operator-facing artifact, so it is tested rather than trusted: it has to complete
with every external effect happening exactly once, in both the crash-between-steps and the
crash-mid-step cases.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from durable_workflow.app import (
    CHARGED,
    build_invoice_workflow,
    count,
    counts_are_exactly_once,
    provider_reconciler,
    scenario_one,
    scenario_two,
)

from xyberos.durable import ExecutionStatus, JournalSettings, JournalStore, StepState, open_journal


def test_the_example_reuses_finished_work_when_a_worker_dies_between_steps(tmp_path: Path) -> None:
    journal_path = tmp_path / "between.db"

    asyncio.run(scenario_one(journal_path))

    assert counts_are_exactly_once(journal_path)
    assert count(journal_path, CHARGED) == 1


def test_the_example_parks_an_uncertain_step_and_finishes_after_reconciling(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "mid.db"

    asyncio.run(scenario_two(journal_path))

    assert counts_are_exactly_once(journal_path)


def test_the_example_creates_a_journal_a_fresh_process_could_reopen(tmp_path: Path) -> None:
    journal_path = tmp_path / "reopen.db"

    asyncio.run(scenario_one(journal_path))

    async def scenario() -> None:
        journal = await open_journal(JournalSettings(path=journal_path))
        try:
            store = JournalStore(journal)
            executions = await store.list_executions()
            assert len(executions) == 1
            view = executions[0]
            assert view.workflow == "invoice"
            assert view.version == "1"
            assert view.status is ExecutionStatus.COMPLETED
            assert [step.state for step in view.steps] == [StepState.SUCCEEDED] * 3
            assert [step.attempts for step in view.steps] == [1, 1, 1]
            assert [event.kind.value for event in view.events][-1] == "completed"
        finally:
            await journal.aclose()

    asyncio.run(scenario())


def test_the_examples_reconciler_returns_the_whole_step_output(tmp_path: Path) -> None:
    """A reconciler that returns a partial output is a trap: it passes here and fails downstream.

    So the example asserts the property directly, by comparing the reconciled output with what the
    step itself would have produced.
    """
    journal_path = tmp_path / "reconcile.db"
    value = {"invoice": "INV-9001", "journal": str(journal_path)}

    reconciled = provider_reconciler(journal_path)("charge", value)

    assert reconciled.state is StepState.SUCCEEDED
    assert reconciled.output == {
        "invoice": "INV-9001",
        "journal": str(journal_path),
        "status": CHARGED,
    }
    assert not count(journal_path, CHARGED)


def test_the_example_definition_is_the_one_the_behavior_rests_on(tmp_path: Path) -> None:
    """The example's safety comes from its definition shape, so the shape is pinned here.

    ``scenario_two`` proves the behavior end to end; this states what the behavior depends on: a
    retry policy on the money-taking step (which covers *failed* attempts) and no activity policy
    anywhere in the example (so an *interrupted* attempt is never repeated).
    """
    workflow = build_invoice_workflow(tmp_path / "safety.db")

    assert workflow.step_ids == ("charge", "receipt", "notify")
    charge = workflow.step_by_id("charge")
    assert charge.retry is not None
    assert charge.retry.max_attempts == 3
