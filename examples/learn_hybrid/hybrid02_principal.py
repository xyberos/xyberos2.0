"""Lesson 2 — a verified principal, and the permission matrix it is measured against.

Run it with:

    python -m learn_hybrid.hybrid02_principal
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
#: The same agent in somebody else's tenant: the same roles, and no sight of acme's tickets.
OTHER_TENANT = VERIFIER.headers("sam@desk", "globex", ["support_agent"])


def main() -> None:
    """Ask three principals for the same rows, and one of them for something they may not do."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            client.post(
                "/tickets",
                json={"subject": "Where is my refund?", "body": "Order 42 came back on Monday."},
                headers=ADA,
            )
            client.post(
                "/tickets",
                json={"subject": "The badge reader is broken", "body": "It flashes."},
                headers=ADA,
            )

            anonymous = client.get("/tickets")
            print("no assertion ->", anonymous.status_code, anonymous.json()["error"]["message"])

            forged = dict(ADA, **{"X-Principal-Signature": "0" * 64})
            refused = client.get("/tickets", headers=forged)
            print("a forged signature ->", refused.status_code, refused.json()["error"]["message"])

            ada = client.get("/tickets", headers=ADA).json()
            print("ada sees:", ada["total"], [item["subject"] for item in ada["items"]])
            print("grace sees:", client.get("/tickets", headers=GRACE).json()["total"])
            print("sam (an agent) sees:", client.get("/tickets", headers=SAM).json()["total"])

            denied = client.post("/tickets/1/classify", headers=GRACE)
            print(
                "a requester classifying ->",
                denied.status_code,
                denied.json()["error"]["message"],
            )

            print(
                "another tenant's agent sees:",
                client.get("/tickets", headers=OTHER_TENANT).json()["total"],
            )
            missing = client.get("/tickets/1", headers=OTHER_TENANT)
            print(
                "and reading acme's ticket 1 ->",
                missing.status_code,
                missing.json()["error"]["message"],
            )


if __name__ == "__main__":
    main()
