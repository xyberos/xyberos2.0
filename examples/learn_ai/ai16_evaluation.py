"""Lesson 16 — evaluation: accuracy, grounding, latency, and cost as rows.

Run it with:

    python -m learn_ai.ai16_evaluation
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from sqlalchemy import Boolean, Column, Float, Integer, MetaData, String, Table, insert, select

from xyberos import App, Inject
from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    Message,
    ModelCapabilities,
    ModelReply,
    Usage,
)
from xyberos.database import DatabaseProvider, temporary_database

CLASSIFY_PROMPT = "Classify the request into one intent."

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["refund", "status", "complaint", "other"]},
        "citation": {"type": "string"},
    },
    "required": ["intent", "citation"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Case:
    """One labelled example: what was asked, and what the application expects."""

    request: str
    expected: str
    passages: tuple[str, ...]


CASES = (
    Case("How long does a refund take?", "refund", ("passage-1: refunds take three days",)),
    Case("Is T-101 still open?", "status", ("passage-2: T-101 is open",)),
    Case(
        "This is the third time I have asked",
        "complaint",
        ("passage-3: escalations go to quality",),
    ),
)

metadata = MetaData()

results = Table(
    "results",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("request", String(400), nullable=False),
    Column("expected", String(40), nullable=False),
    Column("actual", String(40), nullable=False),
    Column("correct", Boolean, nullable=False),
    Column("grounded", Boolean, nullable=False),
    Column("latency_ms", Float, nullable=False),
    Column("tokens", Integer, nullable=False),
)


class EvaluationStore:
    """One row per case, which is what makes a quality claim checkable later."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def create_schema(self) -> None:
        async with self._database.transaction() as connection:
            await connection.run_sync(metadata.create_all)

    async def record(self, row: dict[str, object]) -> None:
        async with self._database.transaction() as connection:
            await connection.execute(insert(results).values(**row))

    async def all(self) -> list[dict[str, object]]:
        async with self._database.transaction() as connection:
            found = (await connection.execute(select(results).order_by(results.c.id))).mappings()
            return [dict(row) for row in found]


async def classify(assistant: AIFacade, case: Case) -> tuple[str, str, int]:
    """Return the model's intent, its citation, and the tokens the call reported."""
    context = "\n".join(case.passages)
    response = await assistant.chat(
        ChatRequest(
            messages=(
                Message.system(f"{CLASSIFY_PROMPT} Cite the passage you used."),
                Message.user(f"{context}\n\nRequest: {case.request}"),
            ),
            response_schema=SCHEMA,
        )
    )
    payload = response.structured
    assert isinstance(payload, Mapping)
    return str(payload["intent"]), str(payload["citation"]), response.usage.total_tokens


async def main() -> None:
    """Score three labelled cases and report accuracy, grounding, and cost."""
    provider = FakeModelProvider(
        [
            ModelReply.json_payload(
                {"intent": "refund", "citation": "passage-1"}, usage=Usage(20, 8)
            ),
            ModelReply.json_payload(
                {"intent": "status", "citation": "passage-2"}, usage=Usage(18, 6)
            ),
            ModelReply.json_payload({"intent": "refund", "citation": "none"}, usage=Usage(22, 7)),
        ],
        capabilities=ModelCapabilities(structured_output=True),
    )
    assistant = AIFacade(provider)
    token_total = 0

    app = App()
    async with temporary_database() as database:
        app.provide(DatabaseProvider, instance=database)
        app.provide(EvaluationStore)
        async with app.lifespan():
            store = await app.resolve(EvaluationStore)
            await store.create_schema()

            for case in CASES:
                started = time.perf_counter()
                intent, citation, tokens = await classify(assistant, case)
                grounded = any(citation in passage for passage in case.passages)
                token_total += tokens
                await store.record(
                    {
                        "request": case.request,
                        "expected": case.expected,
                        "actual": intent,
                        "correct": intent == case.expected,
                        "grounded": grounded,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                        "tokens": tokens,
                    }
                )

            rows = await store.all()
            hits = sum(1 for row in rows if row["correct"])
            cited = sum(1 for row in rows if row["grounded"])
            print("cases:     ", len(rows))
            print("accuracy:  ", f"{hits}/{len(rows)}")
            print("grounded:  ", f"{cited}/{len(rows)}")
            print("tokens:    ", token_total)
            print("measured latency: recorded per row, reported as percentiles over many runs")
            for row in rows:
                print(
                    f"  {row['expected']} -> {row['actual']}"
                    f"  correct={row['correct']} grounded={row['grounded']}"
                )


if __name__ == "__main__":
    asyncio.run(main())
