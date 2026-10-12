"""Lesson 10 — retrieval: a similarity query you build over ``embed``.

Run it with:

    python -m learn_ai.ai10_retrieval
"""

from __future__ import annotations

import asyncio
import json
import math

from xyberos.ai import AIFacade, EmbeddingRequest, FakeModelProvider

DOCUMENTS = {
    "policy.md": (
        "Refunds are issued to the original payment method.",
        "A refund takes three business days to appear on a statement.",
        "Orders older than ninety days are handled by the billing team.",
    ),
    "pricing.md": (
        "The enterprise plan is billed annually.",
        "Seats can be added at any time during the term.",
    ),
}
QUESTION = "How long does a refund take?"


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Return the cosine similarity of two vectors, or 0.0 when either has no length."""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_length = math.sqrt(sum(a * a for a in left))
    right_length = math.sqrt(sum(b * b for b in right))
    if not left_length or not right_length:
        return 0.0
    return dot / (left_length * right_length)


async def embed(assistant: AIFacade, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
    """Embed every text in one request, which is the cheapest way to use a provider."""
    response = await assistant.embed(EmbeddingRequest(inputs=texts))
    return response.embeddings


async def main() -> None:
    """Store passages with their vectors, then rank them against a question."""
    provider = FakeModelProvider()
    assistant = AIFacade(provider)

    stored: list[tuple[str, int, str, tuple[float, ...]]] = []
    for source, passages in DOCUMENTS.items():
        vectors = await embed(assistant, passages)
        for ordinal, (text, vector) in enumerate(zip(passages, vectors, strict=True)):
            stored.append((source, ordinal, text, vector))
    print("passages stored:", len(stored))
    print("vector width:  ", len(stored[0][3]))

    (question_vector,) = await embed(assistant, (QUESTION,))
    ranked = sorted(
        (
            (cosine(question_vector, vector), source, ordinal, text)
            for source, ordinal, text, vector in stored
        ),
        reverse=True,
    )
    print("question:", QUESTION)
    for score, source, ordinal, text in ranked[:3]:
        print(f"  {round(score, 4)}  {source}#{ordinal}  {text}")
    print("one stored vector:", len(json.dumps(list(stored[0][3]))), "characters of JSON")
    print(
        "this order is procedural, not semantic: the deterministic provider hashes text instead of"
    )
    print(
        "representing meaning, so every passage scores the same - with a real embedding model the"
    )
    print(
        "refund passage ranks first, and lesson 16 is how you measure that rather than assume it."
    )


if __name__ == "__main__":
    asyncio.run(main())
