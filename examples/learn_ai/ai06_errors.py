"""Lesson 6 — failures, timeouts, and the retry that is worth having.

Run it with:

    python -m learn_ai.ai06_errors
"""

from __future__ import annotations

import asyncio

from xyberos import Retry, StepContext, Workflow, seconds
from xyberos.ai import AIFacade, ChatRequest, FakeModelProvider, Message, ModelReply
from xyberos.errors import AIError, TransientError

QUESTION = "Will it rain?"


async def ask(assistant: AIFacade) -> str:
    """One model call, as a caller sees it."""
    response = await assistant.chat(ChatRequest(messages=(Message.user(QUESTION),)))
    return response.message.content


def retrying_step(provider: FakeModelProvider) -> Workflow:
    """Wrap one model call in a workflow step that retries a transient failure."""

    async def ask_step(value: str, context: StepContext) -> str:
        return await ask(AIFacade(provider))

    return Workflow("ask-once", version="1", input_type=str).step(
        "ask", ask_step, retry=Retry(max_attempts=2)
    )


async def failure(provider: FakeModelProvider) -> str:
    """Return how one scripted failure is classified, or the answer if it succeeds."""
    try:
        return await ask(AIFacade(provider))
    except AIError as error:
        return f"{type(error).__name__} | transient: {isinstance(error, TransientError)}"


async def main() -> None:
    """Three failures and the two different conclusions they lead to."""
    transient = FakeModelProvider([ModelReply.transient(), ModelReply.ok("Answered on attempt 2.")])
    result = await retrying_step(transient).run(input=QUESTION, timeout=seconds(5))
    print("after a transient failure:", result.value, f"(calls: {transient.calls})")

    print("a timeout:   ", await failure(FakeModelProvider([ModelReply.timeout()])))
    print("a refusal:   ", await failure(FakeModelProvider([ModelReply.refusal(content="No.")])))
    print("rate limited:", await failure(FakeModelProvider([ModelReply.rate_limited()])))


if __name__ == "__main__":
    asyncio.run(main())
