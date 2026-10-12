"""Lesson 2 — providers declare what they can do, and the facade checks.

Run it with:

    python -m learn_ai.ai02_providers
"""

from __future__ import annotations

import asyncio

from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    Message,
    ModelCapabilities,
    ModelReply,
)
from xyberos.errors import AIUnsupportedCapabilityError

CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {"category": {"type": "string", "enum": ["refund", "question", "complaint"]}},
    "required": ["category"],
    "additionalProperties": False,
}


async def describe(assistant: AIFacade, label: str) -> None:
    """Print what a facade's provider declares, then ask it for structured output."""
    print(f"{label}: {assistant.name} {assistant.model}")
    print(f"{label} capabilities:", assistant.capabilities)
    request = ChatRequest(
        messages=(Message.user("Classify this ticket."),),
        response_schema=CATEGORY_SCHEMA,
    )
    try:
        await assistant.structured(request)
    except AIUnsupportedCapabilityError as error:
        print(f"{label} refused:", error)
    else:
        print(f"{label} answered")


async def main() -> None:
    """One provider that declares structured output, one that does not."""
    capable = FakeModelProvider(
        [ModelReply.json_payload({"category": "complaint"})],
        capabilities=ModelCapabilities(structured_output=True),
    )
    incapable = FakeModelProvider(capabilities=ModelCapabilities())

    await describe(AIFacade(capable), "declares it")
    await describe(AIFacade(incapable), "does not")


if __name__ == "__main__":
    asyncio.run(main())
