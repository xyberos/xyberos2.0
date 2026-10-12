"""Lesson 3 — the audit log: who did what, written in the same transaction as the change.

Run it with:

    python -m learn_hybrid.hybrid03_audit
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
GRACE = VERIFIER.headers("grace@example.com", "acme", ["requester"])
SAM = VERIFIER.headers("sam@desk", "acme", ["support_agent"])


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADA)
            client.post(
                "/tickets",
                json={"subject": "Where is my refund?", "body": "Order 42 came back on Monday."},
            )

            client.headers.update(SAM)
            client.post("/tickets/1/classify")
            client.post("/tickets/1/draft")
            client.post("/tickets/1/approve")

            trail = client.get("/tickets/1/audit").json()["events"]
            for event in trail:
                print(f"{event['action']:<10} by {event['actor']:<18} {event['detail']}")

            client.headers.update(ADA)
            print(
                "the requester reads the same trail:",
                len(client.get("/tickets/1/audit").json()["events"]),
            )

            client.headers.update(GRACE)
            other = client.get("/tickets/1/audit")
            print(
                "another requester reads it ->",
                other.status_code,
                other.json()["error"]["message"],
            )

            approved = [event for event in trail if event["action"] == "approved"][0]
            print("the audit row keeps the approved body:", approved["detail"])


if __name__ == "__main__":
    main()
