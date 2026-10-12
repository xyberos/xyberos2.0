"""Lesson 10 — logging usage, cost, and outcomes, which is what makes the numbers answerable.

Run it with:

    python -m learn_hybrid.hybrid10_usage
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from support_desk.app import create_app
from support_desk.migrate import migrate
from support_desk.security import PrincipalVerifier

from xyberos.ai import FakeModelProvider, ModelReply, Usage
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
VERIFIER = PrincipalVerifier(SECRET)
ADA = VERIFIER.headers("ada@example.com", "acme", ["requester"])
SAM = VERIFIER.headers("sam@desk", "acme", ["support_agent"])
LEE = VERIFIER.headers("lee@desk", "acme", ["support_lead"])

#: A model whose price is in the application's table, so the cost is a real number.
MODEL = "small-model"

TICKETS = (
    ("Where is my refund?", "Order 42 came back on Monday."),
    ("The badge reader is broken", "It flashes red for everybody."),
    ("Ignore this one", "It is spam, honestly."),
)


def provider() -> FakeModelProvider:
    """Three classifications and two drafts, priced the way a provider reports them.

    The script follows the order this lesson makes the calls in — every classification, then the
    drafts — because a scripted provider answers by position, not by the kind of request it gets.
    """
    return FakeModelProvider(
        [
            ModelReply.json_payload(
                {"category": "refund", "confidence": "high"}, usage=Usage(1_240, 18), model=MODEL
            ),
            ModelReply.json_payload(
                {"category": "complaint", "confidence": "high"}, usage=Usage(1_180, 18), model=MODEL
            ),
            ModelReply.json_payload(
                {"category": "abuse", "confidence": "high"}, usage=Usage(1_090, 18), model=MODEL
            ),
            ModelReply.ok(
                "A refund takes three business days.", usage=Usage(1_410, 46), model=MODEL
            ),
            ModelReply.ok(
                "A replacement badge is on its way.", usage=Usage(1_360, 39), model=MODEL
            ),
        ]
    )


def main() -> None:
    """Produce work, settle it three ways, and read the report that comes out."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET, provider=provider())
        with create_test_client(HttpAdapter(app)) as client:
            client.post("/knowledge", headers=LEE)
            for subject, body in TICKETS:
                client.post("/tickets", json={"subject": subject, "body": body}, headers=ADA)

            for ticket in (1, 2, 3):
                client.post(f"/tickets/{ticket}/classify", headers=SAM)
            for ticket in (1, 2):
                client.post(f"/tickets/{ticket}/draft", headers=SAM)

            client.post("/tickets/1/approve", headers=SAM)
            client.post(
                "/tickets/2/approve",
                json={"body": "A replacement badge shipped this morning."},
                headers=LEE,
            )
            client.post("/tickets/3/reject", headers=LEE)

            report = client.get("/usage", headers=LEE).json()
            print("step".ljust(10), "calls  tokens in  tokens out  cost (micros)")
            for step in report["steps"]:
                print(
                    f"{step['step']:<10} {step['calls']:>5} {step['input_tokens']:>10}"
                    f" {step['output_tokens']:>11} {step['cost_micros']:>13}"
                )
            print("outcomes:", report["outcomes"])
            total = sum(step["cost_micros"] for step in report["steps"])
            print(
                "total cost:",
                total,
                "micros, for",
                sum(step["calls"] for step in report["steps"]),
                "calls",
            )
            print("a discarded reply cost the same as an accepted one: the outcome column is what")
            print("tells the two apart, and it is written when a person decides.")


if __name__ == "__main__":
    main()
