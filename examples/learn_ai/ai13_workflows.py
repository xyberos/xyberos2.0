"""Lesson 13 — workflows: explicit steps, edges, branches, and deadlines.

Run it with:

    python -m learn_ai.ai13_workflows
"""

from __future__ import annotations

import asyncio
from typing import Any

from xyberos import Retry, StepContext, Workflow, seconds
from xyberos.errors import WorkflowValidationError


def build() -> Workflow:
    """Define the graph once, so it can be rendered, tested, and reviewed without running it."""

    async def classify(value: dict[str, str], context: StepContext) -> dict[str, str]:
        text = value["request"].lower()
        intent = "other" if "refund" not in text else "refund"
        return {"request": value["request"], "intent": intent}

    async def search(value: dict[str, str], context: StepContext) -> dict[str, str]:
        return {**value, "passage": "a refund takes three business days"}

    async def answer(value: dict[str, str], context: StepContext) -> str:
        return f"About your {value['intent']}: {value['passage']}"

    async def escalate(value: dict[str, str], context: StepContext) -> str:
        return "This needs a person."

    return (
        Workflow("triage", version="1", input_type=dict)
        .step("classify", classify, retry=Retry(max_attempts=2), timeout=seconds(5))
        .step("search", search, timeout=seconds(5))
        .step("answer", answer)
        .step("escalate", escalate)
        .edge("classify", "search", when=lambda value: value["intent"] != "other")
        .edge("classify", "escalate", when=lambda value: value["intent"] == "other")
        .edge("search", "answer")
    )


def cyclic() -> Workflow:
    """A graph with a cycle, which validation refuses before anything runs."""

    async def step(value: str, context: StepContext) -> str:
        return value

    return (
        Workflow("loop", version="1", input_type=str)
        .step("a", step)
        .step("b", step)
        .edge("a", "b")
        .edge("b", "a")
    )


async def main() -> None:
    """Render the graph, run both branches, and watch validation refuse a loop."""
    workflow = build()
    print(workflow.render().splitlines()[0])
    print("steps:", workflow.step_ids)
    print("entries:", [step.id for step in workflow.entries])
    print("exits:  ", [step.id for step in workflow.exits])

    for request in ("how long does a refund take?", "the printer is on fire"):
        result: Any = await workflow.run(input={"request": request}, timeout=seconds(10))
        print(f"{request!r} -> {result.value}")
        statuses = {step_id: outcome.status.value for step_id, outcome in result.steps.items()}
        print("   steps:", statuses)

    try:
        cyclic().validate()
    except WorkflowValidationError as error:
        print("a cycle is refused:", error)


if __name__ == "__main__":
    asyncio.run(main())
