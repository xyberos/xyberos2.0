"""Retrieval the application owns: passages, vectors, and a similarity query.

The package gives an application ``embed`` and nothing else. There is no document loader, no
chunker, no index, and no vector store, so this module is what "you build it" means in practice: the
rows, the cut, the arithmetic, and the honesty about what the arithmetic proves.
"""

from __future__ import annotations

import json
import math
from typing import Annotated

from sqlalchemy import insert, select

from support_desk.tables import passages
from xyberos import Inject
from xyberos.ai import AIFacade, EmbeddingRequest
from xyberos.database import DatabaseProvider

#: What the desk knows, a passage at a time. Cutting on blank lines keeps a paragraph whole, which
#: is the simplest rule that does not split the sentence that made a passage true.
ARTICLES: dict[str, str] = {
    "refunds.md": (
        "Refunds are issued to the original payment method.\n\n"
        "A refund takes three business days to appear on a statement.\n\n"
        "Orders older than ninety days are handled by the billing team."
    ),
    "badges.md": (
        "A badge that stops working is usually a battery, not an account problem.\n\n"
        "Replacement badges are shipped within two business days of a request."
    ),
    "accounts.md": (
        "Seats can be added at any time during the term of an enterprise plan.\n\n"
        "An account is closed when its last administrator asks for it to be closed."
    ),
}


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Return the cosine similarity of two vectors, or 0.0 when either has no length."""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_length = math.sqrt(sum(a * a for a in left))
    right_length = math.sqrt(sum(b * b for b in right))
    if not left_length or not right_length:
        return 0.0
    return dot / (left_length * right_length)


def split(text: str) -> list[str]:
    """Split a document into passages, one paragraph each."""
    return [" ".join(block.split()) for block in text.split("\n\n") if block.strip()]


class KnowledgeBase:
    """The articles the desk may quote, stored with their vectors."""

    def __init__(
        self,
        database: Annotated[DatabaseProvider, Inject()],
        assistant: Annotated[AIFacade, Inject()],
    ) -> None:
        self._database = database
        self._assistant = assistant

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        """Embed every text in one request, which is the cheapest way to use a provider."""
        response = await self._assistant.embed(EmbeddingRequest(inputs=texts))
        return response.embeddings

    async def index(self, articles: dict[str, str] | None = None) -> int:
        """Embed and store the articles, and return how many passages that made."""
        documents = ARTICLES if articles is None else articles
        stored = 0
        for source, text in documents.items():
            chunks = split(text)
            vectors = await self.embed(tuple(chunks))
            async with self._database.transaction() as connection:
                for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                    await connection.execute(
                        insert(passages).values(
                            source=source,
                            ordinal=ordinal,
                            text=chunk,
                            vector=json.dumps(list(vector)),
                        )
                    )
                    stored += 1
        return stored

    async def search(self, question: str, *, limit: int = 2) -> list[dict[str, object]]:
        """Return the passages closest to a question, best first.

        The similarity is arithmetic over what the provider returned, so what it proves depends on
        the provider: with a real embedding model the refund passage wins for a refund question, and
        with the deterministic one every vector is a hash of its text and the ranking is procedural.
        That difference is the reason lesson 16 of the AI path exists.
        """
        (question_vector,) = await self.embed((question,))
        async with self._database.transaction() as connection:
            rows = (
                (await connection.execute(select(passages).order_by(passages.c.id)))
                .mappings()
                .all()
            )
        ranked = sorted(
            (
                {
                    "score": cosine(question_vector, tuple(json.loads(str(row["vector"])))),
                    "source": row["source"],
                    "ordinal": row["ordinal"],
                    "text": row["text"],
                }
                for row in rows
            ),
            key=lambda hit: (-float(hit["score"]), str(hit["source"]), int(hit["ordinal"])),
        )
        return ranked[:limit]
