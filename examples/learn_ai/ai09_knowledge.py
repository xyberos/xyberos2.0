"""Lesson 9 — knowledge: documents in, passages out.

Run it with:

    python -m learn_ai.ai09_knowledge
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select

from xyberos import App, Inject
from xyberos.database import DatabaseProvider, temporary_database

POLICY = """Refunds are issued to the original payment method.

A refund takes three business days to appear on a statement.

Orders older than ninety days are handled by the billing team."""

PRICING = """The enterprise plan is billed annually.

Seats can be added at any time during the term."""

metadata = MetaData()

passages = Table(
    "passages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(120), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("text", String(2000), nullable=False),
)


def split(text: str) -> list[str]:
    """Split a document into passages.

    Cutting on blank lines is the simplest rule that keeps a paragraph whole. Real chunking trades
    context against precision: a passage too long dilutes what it matches, and one too short loses
    the sentence that made it true. Where you cut decides what retrieval can find later.
    """
    return [" ".join(block.split()) for block in text.split("\n\n") if block.strip()]


class KnowledgeBase:
    """The documents the application owns, as rows it can query.

    There is no document loader in the package: loading, splitting, and storing are the
    application's decisions, and this is the smallest honest version of them.
    """

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def create_schema(self) -> None:
        """Create the table, which a real application would do with a migration."""
        async with self._database.transaction() as connection:
            await connection.run_sync(metadata.create_all)

    async def add(self, source: str, text: str) -> int:
        """Store one document as numbered passages, and return how many."""
        chunks = split(text)
        async with self._database.transaction() as connection:
            for ordinal, chunk in enumerate(chunks):
                await connection.execute(
                    insert(passages).values(source=source, ordinal=ordinal, text=chunk)
                )
        return len(chunks)

    async def all(self, *, source: str | None = None) -> list[dict[str, object]]:
        """Return the stored passages, optionally for one source, in document order."""
        statement = select(passages).order_by(passages.c.source, passages.c.ordinal)
        if source is not None:
            statement = statement.where(passages.c.source == source)
        async with self._database.transaction() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]


async def main() -> None:
    """Load two documents, and read back the passages they became."""
    app = App()
    async with temporary_database() as database:
        app.provide(DatabaseProvider, instance=database)
        app.provide(KnowledgeBase)
        async with app.lifespan():
            knowledge = await app.resolve(KnowledgeBase)
            await knowledge.create_schema()

            print("policy passages:", await knowledge.add("policy.md", POLICY))
            print("pricing passages:", await knowledge.add("pricing.md", PRICING))

            stored = await knowledge.all()
            print("stored:", [(row["source"], row["ordinal"]) for row in stored])
            print("second passage:", stored[1]["text"])
            print("dimensions:", len(str(stored[1]["text"]).split()))


if __name__ == "__main__":
    asyncio.run(main())
