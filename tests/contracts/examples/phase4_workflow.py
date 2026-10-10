"""Executable Phase 4 contract: an inspectable workflow with retries and a deadline.

This mirrors the contract in ``docs/implementation.md``. The step functions are plain async code
with declared input and output types, the definition is a value that can be inspected before it
runs, and the run carries its own budget.
"""

import asyncio

from xyberos import Retry, StepContext, Workflow, seconds


async def retrieve_documents(value: dict[str, str], context: StepContext) -> list[str]:
    return [f"document-for-{value['ticket']}"]


async def generate_answer(value: list[str], context: StepContext) -> str:
    return f"answer from {len(value)} document(s): {value[0]}"


def build_workflow() -> Workflow:
    return (
        Workflow("support", version="1")
        .step("retrieve", retrieve_documents, retry=Retry(max_attempts=3))
        .step("answer", generate_answer, timeout=seconds(30))
        .edge("retrieve", "answer")
    )


async def main() -> None:
    workflow = build_workflow()
    workflow.validate()

    assert workflow.render().startswith("workflow 'support' version='1'")

    result = await workflow.run(input={"ticket": "T-1"}, timeout=seconds(45))

    assert result.value == "answer from 1 document(s): document-for-T-1"
    assert dict(result.outputs) == {"answer": "answer from 1 document(s): document-for-T-1"}
    assert result.outcome("retrieve").attempt_count == 1
    assert result.outcome("retrieve").status.value == "succeeded"


if __name__ == "__main__":
    asyncio.run(main())
