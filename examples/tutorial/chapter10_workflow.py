"""Chapter 10 — doing several things in order.

Run it with:

    python examples/tutorial/chapter10_workflow.py
"""

from __future__ import annotations

import asyncio

from xyberos import Backoff, Retry, StepContext, Workflow, WorkflowEvent
from xyberos.execution import FakeExternalService, ManualClock, Reply, WorkflowExecutor


def build_workflow(service: FakeExternalService) -> Workflow:
    """Build the definition: steps first, then the edges between them."""

    async def fetch(ticket: str, context: StepContext) -> str:
        return str(await service.call(ticket=ticket))

    async def classify(ticket: str, context: StepContext) -> str:
        return "urgent" if "urgent" in ticket else "normal"

    async def notify(ticket: str, context: StepContext) -> str:
        return f"notified about {ticket}"

    async def archive(ticket: str, context: StepContext) -> str:
        return f"archived {ticket}"

    return (
        Workflow("tutorial-triage", version="1", input_type=str)
        .step("fetch", fetch, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.5)))
        .step("classify", classify)
        .step("notify", notify)
        .step("archive", archive)
        .edge("fetch", "classify")
        .edge("classify", "notify", when=lambda value: value == "urgent")
        .edge("classify", "archive")
    )


async def main() -> None:
    clock = ManualClock()
    service = FakeExternalService([Reply.rate_limited(), Reply.ok("T-urgent-100")], clock=clock)
    workflow = build_workflow(service)
    events: list[WorkflowEvent] = []

    print("workflow:", workflow.name, "version", workflow.version)
    print("steps:", [step.id for step in workflow.steps])

    task = asyncio.ensure_future(
        workflow.run(
            input="T-urgent-100",
            executor=WorkflowExecutor(clock=clock),
            on_event=events.append,
        )
    )
    result = await clock.drive(task)

    print("result:", result.value)
    print("service calls:", service.calls)
    print("virtual time used:", clock.monotonic())
    print("events:")
    for event in events:
        print("  ", event.render())


if __name__ == "__main__":
    asyncio.run(main())
