"""Lesson 5 — structured output over a closed schema subset.

Run it with:

    python -m learn_ai.ai05_structured
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    Message,
    ModelCapabilities,
    ModelReply,
    check_schema,
    describe_schema,
)
from xyberos.errors import AIError, AISchemaError

CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["refund", "question", "complaint"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["category", "confidence"],
    "additionalProperties": False,
}

UNSUPPORTED_SCHEMA = {
    "type": "object",
    "properties": {"category": {"type": "string"}},
    "oneOf": [{"required": ["category"]}],
}


async def classify(provider: FakeModelProvider) -> object:
    """Ask one provider to classify a ticket, and return what the facade accepted."""
    assistant = AIFacade(provider)
    return await assistant.structured(
        ChatRequest(
            messages=(Message.system("Classify the ticket."), Message.user("My badge stopped.")),
            response_schema=CATEGORY_SCHEMA,
        )
    )


async def main() -> None:
    """One schema, three answers: accepted, wrong, and unparseable."""
    check_schema(CATEGORY_SCHEMA, location="lesson")
    print("the schema is usable:", describe_schema(CATEGORY_SCHEMA))

    capable = ModelCapabilities(structured_output=True)
    good = FakeModelProvider(
        [ModelReply.json_payload({"category": "complaint", "confidence": "high"})],
        capabilities=capable,
    )
    accepted = await classify(good)
    assert isinstance(accepted, Mapping)
    print("accepted:", dict(accepted))

    wrong = FakeModelProvider(
        [ModelReply.wrong_shape({"category": "banana", "confidence": "high"})],
        capabilities=capable,
    )
    try:
        await classify(wrong)
    except AISchemaError as error:
        print("refused:", error)

    unparseable = FakeModelProvider(
        [ModelReply.malformed(content="I think it is a complaint.")],
        capabilities=capable,
    )
    try:
        await classify(unparseable)
    except AIError as error:
        print("unparseable:", type(error).__name__, error)

    try:
        check_schema(UNSUPPORTED_SCHEMA, location="lesson")
    except AIError as error:
        print("a schema outside the subset:", type(error).__name__, error)


if __name__ == "__main__":
    asyncio.run(main())
