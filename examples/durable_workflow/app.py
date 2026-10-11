"""Durable workflows: progress that outlives the worker that was running it.

Run it with ``python -m durable_workflow.app`` from the ``examples`` directory. This needs the
``durable`` extra: ``pip install "xyberos[durable]"``.

Two scenarios, both deterministic and both read from the journal rather than from memory:

1. **A worker dies between steps.** Everything it finished is in the journal, so the next worker
   picks up the next step and no effect happens twice.
2. **A worker dies mid-step.** Its effect may already have happened, and nothing can prove whether
   it did. Recovery refuses to guess: the step is recorded as ``outcome_unknown`` and the run is
   parked until a reconciler — the caller's own way of asking the outside world — decides.

Each step appends a line to a side-effect log, so the printed counts show exactly how many times
each external effect actually happened.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from xyberos import Backoff, Retry, StepContext, Workflow
from xyberos.durable import (
    ExecutionStatus,
    ExecutionView,
    Journal,
    JournalSettings,
    JournalStore,
    Reconciliation,
    StepState,
    open_journal,
)
from xyberos.durable.recovery import recover
from xyberos.durable.testing import expire_leases
from xyberos.durable.worker import DurableWorker, WorkerSettings

WORK_DIR = Path("var/durable_workflow")

CHARGED = "charged"
RECEIPTED = "receipted"
NOTIFIED = "notified"


def effects_path(journal_path: Path) -> Path:
    """Return the side-effect log this example appends to."""
    return journal_path.with_suffix(".effects")


def record(journal_path: Path, name: str) -> None:
    """Append one line: the external effect, which the journal does not own."""
    with effects_path(journal_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}\n")


def count(journal_path: Path, name: str) -> int:
    """Return how many times an effect was recorded."""
    path = effects_path(journal_path)
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line == name)


def charge_output(value: dict[str, str]) -> dict[str, str]:
    """Return the value ``charge`` produces.

    The step and its reconciler both call this, and that is the point: a reconciler must produce the
    *complete* output the step would have returned, because downstream steps consume it. A partial
    output is accepted by the journal and then fails later in some unrelated step, which is a
    miserable thing to debug.
    """
    return {"invoice": value["invoice"], "journal": value["journal"], "status": CHARGED}


def build_invoice_workflow(journal_path: Path, *, gate: asyncio.Event | None = None) -> Workflow:
    """Build the three-step invoice definition.

    ``gate`` exists only so the second scenario can hold a step open while the worker is abandoned
    mid-flight; a real step would be waiting on a payment provider instead.
    """

    def mark(value: dict[str, str], name: str) -> dict[str, str]:
        record(Path(value["journal"]), name)
        return {"invoice": value["invoice"], "journal": value["journal"], "status": name}

    async def charge(value: dict[str, str], context: StepContext) -> dict[str, str]:
        # The provider call happens first: this is the "crashed after the external call but before
        # the result was persisted" case, which is the one that cannot be resolved locally.
        record(Path(value["journal"]), CHARGED)
        if gate is not None:
            await gate.wait()
        return charge_output(value)

    async def receipt(value: dict[str, str], context: StepContext) -> dict[str, str]:
        return mark(value, RECEIPTED)

    async def notify(value: dict[str, str], context: StepContext) -> str:
        record(Path(value["journal"]), NOTIFIED)
        return f"invoice {value['invoice']} charged, receipted, and the customer notified"

    return (
        Workflow("invoice", version="1")
        .step("charge", charge, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.05)))
        .step("receipt", receipt)
        .step("notify", notify)
        .edge("charge", "receipt")
        .edge("receipt", "notify")
    )


def worker_for(store: JournalStore, workflow: Workflow, owner: str) -> DurableWorker:
    """Build a worker with the definition it needs, and no activity policy at all."""
    return DurableWorker(
        store,
        {f"{workflow.name}:{workflow.version}": workflow},
        settings=WorkerSettings(owner=owner),
    )


def render(view: ExecutionView) -> None:
    """Print an execution's status, steps, and timeline."""
    print(f"  status: {view.status.value}")
    print(f"  result: {view.result}")
    for step in view.steps:
        detail = f"  ({step.state_detail})" if step.state_detail else ""
        print(f"  step {step.step_id:<8} {step.state.value:<15} attempts={step.attempts}{detail}")
    for event in view.events:
        where = f" step={event.step_id}" if event.step_id else ""
        note = f" {event.detail}" if event.detail else ""
        print(f"    {event.sequence:>3}  {event.kind.value}{where}{note}")


async def wait_until(
    condition: Callable[[], bool], *, description: str, rounds: int = 5000
) -> None:
    """Yield until ``condition`` holds, or fail loudly instead of hanging.

    Polling with ``asyncio.sleep(0)`` only hands control back to the loop, so this never depends on
    wall-clock time; it depends on the other task making progress.
    """
    for _ in range(rounds):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"timed out waiting for {description}")


async def wait_for_step_to_start(store: JournalStore, execution_id: str, step_id: str) -> None:
    """Yield until the journal records ``step_id`` as running."""

    async def started() -> bool:
        return step_id in await store.running_steps(execution_id)

    for _ in range(5000):
        if await started():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"step {step_id!r} never started in execution {execution_id}")


async def run_to_completion(
    store: JournalStore, worker: DurableWorker, execution_id: str, *, steps: int
) -> ExecutionView:
    """Drive a worker until the execution is finished, then return its final view."""
    for _ in range(steps + 1):
        view = await store.inspect(execution_id)
        if view.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED):
            return view
        if await worker.run_once() is None:
            break
    return await store.inspect(execution_id)


async def fresh_journal(journal_path: Path) -> tuple[Journal, JournalStore]:
    """Open a clean journal for one scenario, so its counters and effects stand alone."""
    for stale in (journal_path, effects_path(journal_path)):
        for suffix in ("", "-wal", "-shm"):
            Path(f"{stale}{suffix}").unlink(missing_ok=True)
    journal = await open_journal(JournalSettings(path=journal_path, lease_ttl_seconds=30.0))
    return journal, JournalStore(journal)


def counts(journal_path: Path) -> str:
    """Render the effect counts for a printed summary."""
    return (
        f"charged={count(journal_path, CHARGED)} "
        f"receipted={count(journal_path, RECEIPTED)} "
        f"notified={count(journal_path, NOTIFIED)}"
    )


def counts_are_exactly_once(journal_path: Path) -> bool:
    """Whether every external effect happened exactly once."""
    return all(count(journal_path, name) == 1 for name in (CHARGED, RECEIPTED, NOTIFIED))


async def print_stats(store: JournalStore) -> None:
    """Print the queue counters an operator would watch."""
    stats = await store.stats()
    location = Path(str(stats.detail["paths"]))
    print("   queue counters:")
    print(
        f"   completed={stats.completed} running={stats.running} queued={stats.queued} "
        f"waiting={stats.waiting} expired_leases={stats.expired_leases}"
    )
    print(f"   journal file: {location}")
    print(f"   effect log:   {effects_path(location)}")


def provider_reconciler(journal_path: Path) -> Callable[[str, object], Reconciliation]:
    """Return the reconciler this example uses: it asks the provider what happened.

    A real reconciler calls the provider; this one reads the effect log, which is the same evidence
    in a form the example can print. It returns exactly what the step would have returned -- see
    :func:`charge_output` for why that matters.
    """

    def reconcile(step_id: str, step_input: object) -> Reconciliation:
        if not isinstance(step_input, dict):  # pragma: no cover - the input is the run input
            raise AssertionError(f"the reconciler needs the step input, got {step_input!r}")
        proof = count(journal_path, CHARGED)
        return Reconciliation(
            state=StepState.SUCCEEDED,
            output=charge_output(step_input),
            detail=f"the payment provider confirms one charge (the local log shows {proof})",
        )

    return reconcile


async def scenario_one(journal_path: Path) -> None:
    """A worker dies between steps: the finished work is reused."""
    print("scenario 1 - the worker dies between steps")
    print()
    journal, store = await fresh_journal(journal_path)
    try:
        workflow = build_invoice_workflow(journal_path)
        value = {"invoice": "INV-1001", "journal": str(journal_path)}
        handle = await store.submit(workflow, input=value)
        print(f"1. submitted {handle.execution_id} ({handle.status.value})")

        worker_a = worker_for(store, workflow, owner="invoice-worker-a")
        first = await worker_a.run_once()
        print(f"2. worker A ran one step: {first.action if first else 'nothing to do'}")
        print(f"   effects: charged={count(journal_path, CHARGED)}")
        del worker_a
        print("3. worker A is gone. It had already yielded, so nobody holds a lease for this")
        print("   execution, and nothing was cleaned up on its way out.")
        print()
        print("   what the journal kept:")
        render(await store.inspect(handle.execution_id))

        worker_b = worker_for(store, workflow, owner="invoice-worker-b")
        print()
        print("4. worker B takes over; it has never seen this execution before")
        report = await worker_b.recover()
        print(f"   recovery examined: {report.examined} (the lease had already been released)")
        final = await run_to_completion(
            store, worker_b, handle.execution_id, steps=len(workflow.steps)
        )
        render(final)
        print()
        print("   every step ran exactly once, because none of them was ever in doubt:")
        print(f"   {counts(journal_path)}")
        print()
        await print_stats(store)
        assert final.status is ExecutionStatus.COMPLETED, final.status
        assert counts_are_exactly_once(journal_path)
    finally:
        await journal.aclose()


async def scenario_two(journal_path: Path) -> None:
    """A worker dies mid-step: nothing may be repeated until someone says what happened."""
    print()
    print("scenario 2 - the worker dies in the middle of a step that takes money")
    print()
    journal, store = await fresh_journal(journal_path)
    try:
        gate = asyncio.Event()
        workflow = build_invoice_workflow(journal_path, gate=gate)
        value = {"invoice": "INV-1002", "journal": str(journal_path)}
        handle = await store.submit(workflow, input=value, execution_id="invoice-mid-step")
        print(f"1. submitted {handle.execution_id} ({handle.status.value})")

        worker_a = worker_for(store, workflow, owner="invoice-worker-a")
        task = asyncio.ensure_future(worker_a.run_once())
        await wait_for_step_to_start(store, handle.execution_id, "charge")
        # The interesting crash is the one where the effect has already landed but its result has
        # not, so wait for the effect itself before killing the worker.
        await wait_until(
            lambda: count(journal_path, CHARGED) >= 1,
            description="the charge to be recorded by the in-flight step",
        )
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        print("2. the worker is killed while the step is in flight")
        charged = count(journal_path, CHARGED)
        print(f"   effects: charged={charged} - the charge may have gone through")
        print()
        print("   what the journal kept:")
        render(await store.inspect(handle.execution_id))

        worker_b = worker_for(store, workflow, owner="invoice-worker-b")
        print()
        print("3. worker B cannot take the work: the dead worker's lease is still live")
        idle = await worker_b.run_once()
        print(f"   worker B: {idle.action if idle else 'nothing to claim'}")

        print()
        print("4. the lease runs out. (In a real deployment the clock does this; the example")
        print("   backdates the lease so the outcome is deterministic rather than dependent on a")
        print("   sleep in a test suite.)")
        await expire_leases(journal)
        report = await recover(
            store,
            definitions={f"{workflow.name}:{workflow.version}": workflow},
            owner="recovery",
        )
        print(f"   recovery examined: {report.examined}")
        for execution_id, decision in report.decisions.items():
            print(f"   decision for {execution_id}: {decision}")
        parked = await store.inspect(handle.execution_id)
        render(parked)
        print()
        print("   nothing was re-run: the journal says the charge's outcome is unknown, not that")
        print("   failed. That is the difference between at-least-once and a wrong answer.")
        assert count(journal_path, CHARGED) == 1
        assert parked.status is ExecutionStatus.WAITING
        assert parked.steps[0].state is StepState.OUTCOME_UNKNOWN

        print()
        print("5. the operator supplies a reconciler: ask the payment provider what happened")
        await store.resume_waiting(handle.execution_id, reason="the operator resolved the attempt")
        claim = await store.claim_next("operator-session")
        if claim is None:  # pragma: no cover - the resume above makes the execution claimable
            raise AssertionError("the resumed execution could not be claimed")
        reconciled = provider_reconciler(journal_path)("charge", claim.input)
        await store.resolve_step(
            claim,
            "charge",
            state=reconciled.state,
            output=reconciled.output,
            detail=reconciled.detail,
        )
        print(f"   reconciled: {reconciled.detail}")

        print()
        print("6. the worker finishes the run from the record that was just written")
        final = await run_to_completion(
            store, worker_b, handle.execution_id, steps=len(workflow.steps)
        )
        render(final)
        print()
        print("   the uncertain effect happened exactly once, and the run still finished:")
        print(f"   {counts(journal_path)}")
        print()
        await print_stats(store)
        assert final.status is ExecutionStatus.COMPLETED, final.status
        assert counts_are_exactly_once(journal_path)
    finally:
        await journal.aclose()


async def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    await scenario_one(WORK_DIR / "between-steps.db")
    await scenario_two(WORK_DIR / "mid-step.db")
    print()
    print(f"the journals and effect logs are in {WORK_DIR}")
    print("Remember the scope: single host, one journal file, at-least-once effects.")


if __name__ == "__main__":
    asyncio.run(main())
