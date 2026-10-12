"""Lesson 4 — classification with structured output over the closed schema subset.

Run it with:

    python -m learn_hybrid.hybrid04_classification
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from support_desk.app import create_app
from support_desk.migrate import migrate
from support_desk.security import Principal, PrincipalVerifier
from support_desk.service import CATEGORIES, CONFIDENCES, TicketService
from support_desk.triage import CLASSIFICATION_SCHEMA, Triage

from xyberos.ai import FakeModelProvider, ModelCapabilities, ModelReply, Usage, check_schema
from xyberos.database import SqliteSettings
from xyberos.errors import XyberosError
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
VERIFIER = PrincipalVerifier(SECRET)
ADA = VERIFIER.headers("ada@example.com", "acme", ["requester"])
SAM = VERIFIER.headers("sam@desk", "acme", ["support_agent"])
LEE = VERIFIER.headers("lee@desk", "acme", ["support_lead"])

TICKET = {"subject": "Where is my refund?", "body": "Order 42 came back on Monday."}

#: The three answers a provider can give, and the one thing they all have to do: leave the ticket
#: exactly where it was.
CASES = (
    ("a valid answer", ModelReply.json_payload({"category": "refund", "confidence": "high"})),
    ("the wrong shape", ModelReply.wrong_shape({"category": "banana", "confidence": "high"})),
    ("not JSON at all", ModelReply.malformed(content="I think it is about a refund.")),
)


def classify(reply: ModelReply) -> tuple[int, str, dict[str, object]]:
    """Classify one ticket through the route, and return what a client can see."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)
        provider = FakeModelProvider(
            [reply], capabilities=ModelCapabilities(structured_output=True)
        )
        app = create_app(settings=settings, secret=SECRET, provider=provider)
        with create_test_client(HttpAdapter(app)) as client:
            client.post("/tickets", json=TICKET, headers=ADA)
            response = client.post("/tickets/1/classify", headers=SAM)
            ticket: dict[str, object] = client.get("/tickets/1", headers=SAM).json()
        return response.status_code, response.text, ticket


async def typed_failure() -> None:
    """The same failure seen from inside the application, which is where the type matters."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)
        provider = FakeModelProvider(
            [ModelReply.wrong_shape({"category": "banana", "confidence": "high"})],
            capabilities=ModelCapabilities(structured_output=True),
        )
        app = create_app(settings=settings, secret=SECRET, provider=provider)
        agent = Principal("sam@desk", "acme", frozenset({"support_agent"}))
        async with app.lifespan():
            tickets = await app.resolve(TicketService)
            triage = await app.resolve(Triage)
            await tickets.open_ticket(agent, TICKET["subject"], TICKET["body"])
            try:
                await triage.classify(agent, 1)
            except XyberosError as error:
                print("inside the application:", type(error).__name__, "-", error)


def main() -> None:
    """One schema, one ticket, and the three things a provider can answer with."""
    check_schema(CLASSIFICATION_SCHEMA, location="hybrid lesson 4")
    print("accepted keywords:", sorted(CLASSIFICATION_SCHEMA))
    print("categories:       ", list(CATEGORIES), "confidences:", list(CONFIDENCES))

    for label, reply in CASES:
        status, text, ticket = classify(reply)
        leaked = "banana" in text
        print(
            f"{label:<16} {status} ticket={ticket['state']:<10} leaked the model's text: {leaked}"
        )
        if status == 200:
            print(f"  -> {ticket['category']}/{ticket['confidence']}")

    print(
        "every provider failure looks the same to a client:",
        "the request could not be completed" in text,
    )
    asyncio.run(typed_failure())

    without_structured = FakeModelProvider(
        [ModelReply.json_payload({"category": "refund", "confidence": "high"})],
        capabilities=ModelCapabilities(structured_output=False),
    )
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)
        app = create_app(settings=settings, secret=SECRET, provider=without_structured)
        with create_test_client(HttpAdapter(app)) as client:
            client.post("/tickets", json=TICKET, headers=ADA)
            response = client.post("/tickets/1/classify", headers=SAM)
            print("a model without structured output ->", response.status_code)
            print(
                "  and the ticket is still:", client.get("/tickets/1", headers=SAM).json()["state"]
            )

    priced = FakeModelProvider(
        [ModelReply.json_payload({"category": "question", "confidence": "low"}, usage=Usage(31, 7))]
    )
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)
        app = create_app(settings=settings, secret=SECRET, provider=priced)
        with create_test_client(HttpAdapter(app)) as client:
            client.post(
                "/tickets", json={"subject": "Is there an API?", "body": "Asking."}, headers=ADA
            )
            client.post("/tickets/1/classify", headers=SAM)
            steps = client.get("/usage", headers=LEE).json()["steps"]
            print("the call is recorded:", steps[0]["step"], steps[0]["input_tokens"], "tokens in")


if __name__ == "__main__":
    main()
