"""Lesson 5 — retrieval you build: passages, vectors, and a similarity query.

Run it with:

    python -m learn_hybrid.hybrid05_retrieval
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from support_desk.app import create_app
from support_desk.knowledge import KnowledgeBase
from support_desk.migrate import migrate

from xyberos.database import SqliteSettings

SECRET = "a-secret-the-deployment-keeps"
QUESTION = "How long does a refund take?"


async def main() -> None:
    """Index the desk's articles, then ask one question and read the ranking."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        async with app.lifespan():
            knowledge = await app.resolve(KnowledgeBase)

            print("passages indexed:", await knowledge.index())
            print("question:", QUESTION)
            for hit in await knowledge.search(QUESTION, limit=3):
                print(f"  {hit['score']:.4f}  {hit['source']}#{hit['ordinal']}  {hit['text']}")

            (vector,) = await knowledge.embed((QUESTION,))
            print("vector width:", len(vector))
            print("one vector:", len(json.dumps(list(vector))), "characters of JSON")
            print("every score above is the same because the deterministic provider hashes text")
            print("instead of representing meaning, so the ranking is procedural. A real embedding")
            print(
                "model is what makes the refund passage win - and lesson 16 of the AI path is how"
            )
            print("you measure that instead of assuming it.")


if __name__ == "__main__":
    asyncio.run(main())
