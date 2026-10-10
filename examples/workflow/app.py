"""A support-ticket triage workflow: retries, branching, timeouts, and events.

Run it with ``python -m workflow.app`` from the ``examples`` directory. Everything is
deterministic: the ticketing service is a scripted fake, so no network and no real clock are
involved beyond the short retry backoff.
"""

from __future__ import annotations

import asyncio

from xyberos import (
    Backoff,
    Retry,
    StepContext,
    Workflow,
    WorkflowEvent,
    seconds,
)
from xyberos.execution import FakeExternalService, Reply


def build_workflow(service: FakeExternalService) -> Workflow:
    """Build the triage definition around one external service.

    The step functions close over the service instead of resolving it from a container, which is
    the simplest way to keep a workflow's dependencies explicit.
    """

    async def classify(value: dict[str, str], context: StepContext) -> dict[str, str]:
        response = await service.call(ticket=value["ticket"])
        category = str(response["category"])
        context.logger.info("classified %s as %s", value["ticket"], category)
        return {"ticket": value["ticket"], "category": category}

    async def refund(value: dict[str, str], context: StepContext) -> str:
        return f"refund queued for {value['ticket']}"

    async def escalate(value: dict[str, str], context: StepContext) -> str:
        return f"escalated {value['ticket']} to a human"

    async def notify(value: str, context: StepContext) -> str:
        return f"customer notified: {value}"

    return (
        Workflow("ticket-triage", version="1", input_type=dict)
        .step("classify", classify, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.05)))
        .step("refund", refund, timeout=seconds(5))
        .step("escalate", escalate, timeout=seconds(5))
        .step("notify", notify, timeout=seconds(5))
        .edge("classify", "refund", when=lambda value: value["category"] == "refund")
        .edge("classify", "escalate")
        .edge("refund", "notify")
        .edge("escalate", "notify")
    )


def report(event: WorkflowEvent) -> None:
    print(f"  {event.render()}")


async def run_scenario(replies: list[Reply], ticket: str) -> str:
    service = FakeExternalService(replies)
    workflow = build_workflow(service)

    result = await workflow.run(input={"ticket": ticket}, timeout=seconds(30), on_event=report)

    print(f"  attempts on classify: {result.outcome('classify').attempt_count}")
    print(f"  external calls: {service.calls}")
    print(f"  outputs: {dict(result.outputs)}")
    return str(result.value)


async def main() -> None:
    workflow = build_workflow(FakeExternalService())
    workflow.validate()

    print(workflow.render())
    print()

    print("scenario 1: the service rate limits once, then classifies a refund")
    first = await run_scenario([Reply.rate_limited(), Reply.ok({"category": "refund"})], "T-100")
    assert first == "customer notified: refund queued for T-100"

    print()
    print("scenario 2: the fallback branch escalates")
    second = await run_scenario([Reply.ok({"category": "question"})], "T-200")
    assert second == "customer notified: escalated T-200 to a human"

    print()
    print("scenario 3: a branch that no edge selects leaves that step skipped")
    skipped = build_workflow(FakeExternalService([Reply.ok({"category": "refund"})]))
    result = await skipped.run(input={"ticket": "T-300"}, timeout=seconds(30))
    print(f"  escalate: {result.outcome('escalate').status.value}")
    assert result.outcome("escalate").status.value == "skipped"


if __name__ == "__main__":
    asyncio.run(main())
