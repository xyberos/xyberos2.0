"""Lesson 7 — human approval before sending, which is the rule the path exists to teach.

Run it with:

    python -m learn_hybrid.hybrid07_approval
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
GRACE = VERIFIER.headers("grace@example.com", "acme", ["requester"])
SAM = VERIFIER.headers("sam@desk", "acme", ["support_agent"])
LEE = VERIFIER.headers("lee@desk", "acme", ["support_lead"])

TICKETS = (
    ("Where is my refund?", "Order 42 came back on Monday."),
    ("The badge reader is broken", "It flashes red for everybody."),
    ("Ignore this one", "It is spam, honestly."),
)


def provider() -> FakeModelProvider:
    """A scripted provider: two classifications with their drafts, then one classification."""
    draft = "A refund takes three business days ({category})."
    return FakeModelProvider(
        [
            ModelReply.json_payload({"category": "refund", "confidence": "high"}),
            ModelReply.ok(draft.format(category="refund"), usage=Usage(20, 8)),
            ModelReply.json_payload({"category": "complaint", "confidence": "high"}),
            ModelReply.ok(draft.format(category="complaint"), usage=Usage(20, 8)),
            ModelReply.json_payload({"category": "question", "confidence": "high"}),
        ]
    )


def main() -> None:
    """Approve one draft as it is, send one that was edited, and reject one before it is drafted."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET, provider=provider())
        with create_test_client(HttpAdapter(app)) as client:
            client.post("/knowledge", headers=LEE)
            for subject, body in TICKETS:
                client.post("/tickets", json={"subject": subject, "body": body}, headers=ADA)
            for ticket in (1, 2):
                client.post(f"/tickets/{ticket}/classify", headers=SAM)
                client.post(f"/tickets/{ticket}/draft", headers=SAM)
            client.post("/tickets/3/classify", headers=SAM)

            refused = client.post("/tickets/1/approve", headers=GRACE)
            print(
                "a requester approving ->", refused.status_code, refused.json()["error"]["message"]
            )

            approved = client.post("/tickets/1/approve", headers=SAM).json()
            print("approve ticket 1 ->", approved["state"])
            sent = client.post("/tickets/1/send", headers=SAM).json()
            print("send ticket 1 ->", sent["state"])
            messages = client.get("/tickets/1/sent", headers=SAM).json()["messages"]
            print("the outbox has", len(messages), "message:", messages[0]["body"])

            edited = client.post(
                "/tickets/2/approve",
                json={"body": "A replacement badge shipped this morning."},
                headers=LEE,
            ).json()
            print("approve ticket 2 with an edit ->", edited["state"])
            client.post("/tickets/2/send", headers=LEE)
            print(
                "what was sent:",
                client.get("/tickets/2/sent", headers=LEE).json()["messages"][0]["body"],
            )

            draft = client.get("/tickets/2/draft", headers=LEE).json()
            print("and what the model wrote is still there:", draft["body"])
            print("  the approver:", draft["approved_by"])

            rejected = client.post("/tickets/3/reject", headers=LEE).json()
            print("a lead rejecting ticket 3 ->", rejected["state"], "(nothing was drafted)")
            print("ticket 3 sent:", client.get("/tickets/3/sent", headers=LEE).json()["count"])

            for ticket in (1, 2, 3):
                actions = [
                    event["action"]
                    for event in client.get(f"/tickets/{ticket}/audit", headers=LEE).json()[
                        "events"
                    ]
                ]
                print(f"ticket {ticket} trail:", actions)


if __name__ == "__main__":
    main()
