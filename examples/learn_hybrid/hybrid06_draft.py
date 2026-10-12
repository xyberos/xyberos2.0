"""Lesson 6 — draft replies that are never sent, because nothing in the application sends one.

Run it with:

    python -m learn_hybrid.hybrid06_draft
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from support_desk.app import create_app
from support_desk.migrate import migrate
from support_desk.security import PrincipalVerifier

from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
VERIFIER = PrincipalVerifier(SECRET)
ADA = VERIFIER.headers("ada@example.com", "acme", ["requester"])
SAM = VERIFIER.headers("sam@desk", "acme", ["support_agent"])
LEE = VERIFIER.headers("lee@desk", "acme", ["support_lead"])


def main() -> None:
    """Classify a ticket, draft a reply with a quoted policy, and try to send it."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            client.post("/knowledge", headers=LEE)
            client.post(
                "/tickets",
                json={"subject": "Where is my refund?", "body": "Order 42 came back on Monday."},
                headers=ADA,
            )

            classified = client.post("/tickets/1/classify", headers=SAM).json()
            print("classified as:", classified["category"], "/", classified["confidence"])

            draft = client.post("/tickets/1/draft", headers=SAM).json()
            print("the draft:", draft["body"])
            print("  written by:", draft["model"], "- approved by:", draft["approved_by"])
            print("  the ticket is:", client.get("/tickets/1", headers=SAM).json()["state"])

            sent = client.get("/tickets/1/sent", headers=SAM).json()
            print("messages sent so far:", sent["count"])

            refused = client.post("/tickets/1/send", headers=SAM)
            print("sending the draft ->", refused.status_code, refused.json()["error"]["message"])

            trail = client.get("/tickets/1/audit", headers=SAM).json()["events"]
            print("the trail records the draft, and no send:", [event["action"] for event in trail])
            print("still nothing sent:", client.get("/tickets/1/sent", headers=SAM).json()["count"])


if __name__ == "__main__":
    main()
