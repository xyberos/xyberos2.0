"""Chapter 12 — surviving a crash, carefully. **Experimental.**

Run it with:

    python examples/tutorial/chapter12_durable.py

Durable execution is experimental: the package emits an `ExperimentalWarning` the first time any
process uses it, and the guide states what it does *not* promise. This chapter shows the happy path;
the caveats are what matter, so read `docs/durable.md` before using it for anything that matters.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from xyberos import StepContext, Workflow
from xyberos.durable import (
    ActivityPolicy,
    JournalSettings,
    JournalStore,
    open_journal,
)
from xyberos.durable.worker import DurableWorker, WorkerSettings


def build_workflow() -> Workflow:
    """Two steps: one that is safe to run twice, one that reports what it did."""

    async def reserve(ticket: str, context: StepContext) -> str:
        return f"reserved {ticket}"

    async def confirm(reservation: str, context: StepContext) -> str:
        return f"{reservation} and confirmed"

    return (
        Workflow("tutorial-booking", version="1", input_type=str)
        .step("reserve", reserve)
        .step("confirm", confirm)
        .edge("reserve", "confirm")
    )


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        journal = await open_journal(JournalSettings(path=Path(directory) / "journal.db"))
        try:
            store = JournalStore(journal)
            workflow = build_workflow()
            handle = await store.submit(workflow, input="T-100", execution_id="booking-T-100")
            print("submitted:", handle.execution_id)
            print("before any worker:", (await store.inspect(handle.execution_id)).status.value)

            worker = DurableWorker(
                store,
                {"tutorial-booking:1": workflow},
                activities={
                    "reserve": ActivityPolicy(idempotent=True),
                    "confirm": ActivityPolicy(idempotent=True),
                },
                settings=WorkerSettings(owner="tutorial"),
            )
            while await worker.run_once() is not None:
                pass

            view = await store.inspect(handle.execution_id)
            print("after the worker:", view.status.value)
            print("result:", view.result)
            print("steps:", [(step.step_id, step.state.value) for step in view.steps])
            print("events:", len(view.events))
            print("timeline:")
            for event in view.events:
                print(
                    "  ", event.sequence, event.kind.value, event.step_id or "", event.detail or ""
                )
        finally:
            await journal.aclose()


if __name__ == "__main__":
    asyncio.run(main())
