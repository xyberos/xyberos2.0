"""Lesson 8 — coordinating the steps with a workflow that stops at a draft.

Run it with:

    python -m learn_hybrid.hybrid08_workflow
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from support_desk.app import create_app
from support_desk.knowledge import KnowledgeBase
from support_desk.migrate import migrate
from support_desk.security import Principal
from support_desk.service import TicketService
from support_desk.triage import Triage

from xyberos.ai import FakeModelProvider, ModelReply
from xyberos.database import SqliteSettings

SECRET = "a-secret-the-deployment-keeps"
AGENT = Principal("sam@desk", "acme", frozenset({"support_agent"}))

TICKETS = (
    ("Where is my refund?", "Order 42 came back on Monday."),
    ("Is there an API?", "Just asking, no rush."),
    ("Where is my refund?", "It is the same order again."),
)


def provider() -> FakeModelProvider:
    """A classification and a draft, a low-confidence classification, and a transient failure."""
    return FakeModelProvider(
        [
            ModelReply.json_payload({"category": "refund", "confidence": "high"}),
            ModelReply.ok("A refund takes three business days to appear."),
            ModelReply.json_payload({"category": "question", "confidence": "low"}),
            ModelReply.transient(),
            ModelReply.json_payload({"category": "refund", "confidence": "high"}),
            ModelReply.ok("A refund takes three business days to appear."),
        ]
    )


async def main() -> None:
    """Render the graph, then run it three times: a draft, a flag, and a retried step."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        scripted = provider()
        app = create_app(settings=settings, secret=SECRET, provider=scripted)
        async with app.lifespan():
            tickets = await app.resolve(TicketService)
            triage = await app.resolve(Triage)
            await (await app.resolve(KnowledgeBase)).index()

            workflow = triage.workflow
            print(workflow.render().splitlines()[0])
            print("steps:  ", workflow.step_ids)
            print("entries:", [step.id for step in workflow.entries])
            print("exits:  ", [step.id for step in workflow.exits])

            labels = (
                "a confident ticket",
                "a ticket nobody is sure about",
                "after a transient error",
            )
            for number, ((subject, body), label) in enumerate(zip(TICKETS, labels, strict=True), 1):
                await tickets.open_ticket(AGENT, subject, body)
                result = await triage.run(AGENT, number)
                steps = result["steps"]
                print(f"{label}: ticket={result['state']}")
                print(f"  {steps}")

            trail = await tickets.audit_trail(AGENT, 2)
            print("the flagged ticket says so:", trail[-1]["action"], "-", trail[-1]["detail"])
            print("model calls so far:", scripted.calls, "(the transient failure was retried)")


if __name__ == "__main__":
    asyncio.run(main())
