"""Lesson 12 — intents: a classification, a routing table, and the rules that need no model.

Run it with:

    python -m learn_ai.ai12_intents
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping

from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    Message,
    ModelCapabilities,
    ModelReply,
)
from xyberos.errors import AIError

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["refund", "status", "complaint", "other"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["intent", "confidence"],
    "additionalProperties": False,
}

TICKET_PATTERN = re.compile(r"\bT-\d{3}\b", re.IGNORECASE)

CLASSIFY_PROMPT = "Classify the request into one intent. Answer with the schema's values only."


def route(intent: str) -> str:
    """Return the handler an intent belongs to. The table is application code."""
    return {
        "refund": "billing.refunds",
        "status": "support.tickets",
        "complaint": "support.quality",
    }.get(intent, "support.triage")


async def classify(assistant: AIFacade, request: str) -> Mapping[str, object] | None:
    """Ask the model for an intent, or return None when the call could not be honoured."""
    try:
        structured = await assistant.structured(
            ChatRequest(
                messages=(Message.system(CLASSIFY_PROMPT), Message.user(request)),
                response_schema=INTENT_SCHEMA,
            )
        )
    except AIError:
        return None
    return structured if isinstance(structured, Mapping) else None


async def route_request(assistant: AIFacade, request: str) -> tuple[str, str]:
    """Return the route and why, using the cheapest rule that can decide."""
    found = TICKET_PATTERN.search(request)
    if found is not None:
        return "support.tickets", f"matched {found.group(0).upper()} without a model"

    classified = await classify(assistant, request)
    if classified is None:
        return "support.triage", "the model could not classify it"
    intent = str(classified["intent"])
    confidence = str(classified["confidence"])
    if confidence == "low":
        return "support.triage", f"low confidence for {intent}"
    return route(intent), f"{intent} ({confidence})"


async def main() -> None:
    """Three requests: one a rule answers, one the model answers, one nobody is sure about."""
    provider = FakeModelProvider(
        [
            ModelReply.json_payload({"intent": "refund", "confidence": "high"}),
            ModelReply.json_payload({"intent": "complaint", "confidence": "low"}),
        ],
        capabilities=ModelCapabilities(structured_output=True),
    )
    assistant = AIFacade(provider)

    for request in (
        "Ticket t-101 is still broken",
        "How long does a refund take?",
        "This is getting ridiculous",
    ):
        where, why = await route_request(assistant, request)
        print(f"{request!r} -> {where} ({why})")
    print("model calls:", provider.calls)


if __name__ == "__main__":
    asyncio.run(main())
