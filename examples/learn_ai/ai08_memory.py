"""Lesson 8 — memory is a table and a query, not a framework feature.

Run it with:

    python -m learn_ai.ai08_memory
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select

from xyberos import App, Inject
from xyberos.ai import AIFacade, ChatRequest, FakeModelProvider, Message, ModelReply
from xyberos.database import DatabaseProvider, temporary_database

SYSTEM_PROMPT = "You are a concise support assistant."
SUBJECT = "acme"

metadata = MetaData()

memories = Table(
    "memories",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("subject", String(120), nullable=False),
    Column("kind", String(40), nullable=False),
    Column("text", String(500), nullable=False),
)


class MemoryStore:
    """Rows the application owns, recalled on purpose and put into the prompt by hand.

    There is no framework memory layer, and this is what one looks like when you need it: a table,
    an insert, a query, and a decision about which rows belong in the next request.
    """

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def create_schema(self) -> None:
        """Create the table, which a real application would do with a migration."""
        async with self._database.transaction() as connection:
            await connection.run_sync(metadata.create_all)

    async def remember(self, subject: str, kind: str, text: str) -> None:
        """Store one durable fact about a subject."""
        async with self._database.transaction() as connection:
            await connection.execute(insert(memories).values(subject=subject, kind=kind, text=text))

    async def recall(self, subject: str, *, limit: int = 5) -> list[dict[str, object]]:
        """Return what is remembered about a subject, oldest first."""
        statement = (
            select(memories)
            .where(memories.c.subject == subject)
            .order_by(memories.c.id)
            .limit(limit)
        )
        async with self._database.transaction() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]


def as_system_message(rows: list[dict[str, object]]) -> Message:
    """Turn recalled rows into the one system message the model will see."""
    remembered = "; ".join(f"{row['kind']}={row['text']}" for row in rows)
    return Message.system(f"What you remember about {SUBJECT}: {remembered}")


async def main() -> None:
    """Remember two things, recall them, and show the prompt they produced."""
    provider = FakeModelProvider([ModelReply.ok("A refund takes three business days.")])
    app = App()
    async with temporary_database() as database:
        app.provide(DatabaseProvider, instance=database)
        app.provide(MemoryStore)
        app.provide(AIFacade, instance=AIFacade(provider), eager=True)

        async with app.lifespan():
            memory = await app.resolve(MemoryStore)
            assistant = await app.resolve(AIFacade)
            await memory.create_schema()

            await memory.remember(SUBJECT, "preference", "prefers email over phone")
            await memory.remember(SUBJECT, "fact", "is on the enterprise plan")

            recalled = await memory.recall(SUBJECT)
            print("remembered:", [(row["kind"], row["text"]) for row in recalled])

            request = ChatRequest(
                messages=(as_system_message(recalled), Message.user("How long does a refund take?"))
            )
            response = await assistant.chat(request)
            print("the model saw:", provider.requests[-1].messages[0].content)
            print("answer:", response.message.content)


if __name__ == "__main__":
    asyncio.run(main())
