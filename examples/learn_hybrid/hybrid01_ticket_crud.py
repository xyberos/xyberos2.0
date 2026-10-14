"""Lesson 1 — tickets as ordinary CRUD, in an application that has nothing to do with a model.

Run it with:

    python -m learn_hybrid.hybrid01_ticket_crud
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
#: The assertion travels with the request. There is no ambient caller — and no session standing in
#: for one, though the framework ships sessions for state — which is what makes the next lesson's
#: refusals checkable instead of described.
ADA = PrincipalVerifier(SECRET).headers("ada@example.com", "acme", ["requester"])

TICKETS = [
    {
        "subject": "Where is my refund?",
        "body": "I returned the order on Monday and I have not seen the money.",
    },
    {"subject": "The badge reader is broken", "body": "It flashes red for everybody."},
]


def main() -> None:
    """Open two tickets, read them back, correct one, and refuse two malformed requests."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            print("health:", client.get("/health", headers=ADA).json())

            for payload in TICKETS:
                created = client.post("/tickets", json=payload, headers=ADA).json()
                print(f"POST /tickets -> {created['id']} {created['state']} {created['subject']}")

            page = client.get("/tickets", headers=ADA).json()
            print(f"GET /tickets -> {len(page['items'])} of {page['total']}")
            for item in page["items"]:
                print(f"  #{item['id']} {item['state']}  {item['subject']}")

            edited = client.patch(
                "/tickets/1", json={"subject": "Where is my refund (order 42)?"}, headers=ADA
            )
            print("PATCH /tickets/1 ->", edited.status_code, edited.json()["subject"])

            blank = client.post("/tickets", json={"subject": "   ", "body": "x"}, headers=ADA)
            print(
                "POST /tickets with no subject ->",
                blank.status_code,
                blank.json()["error"]["message"],
            )
            unknown = client.patch("/tickets/1", json={"tenant": "other"}, headers=ADA)
            print(
                "PATCH with an unknown field ->",
                unknown.status_code,
                unknown.json()["error"]["message"],
            )

            rendered = client.get("/tickets/1/page", headers=ADA)
            print("GET /tickets/1/page ->", rendered.status_code)
            print("  the page shows the subject:", "Where is my refund" in rendered.text)


if __name__ == "__main__":
    main()
