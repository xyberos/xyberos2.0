"""Lesson 5 — validating query parameters, and paging the collection.

Run it with:

    python -m learn_traditional.traditional05_pagination
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from user_management.app import create_app
from user_management.identity import PrincipalVerifier
from user_management.migrate import migrate

from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
#: The administrator's assertion, presented once and carried by every request.
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")

EMAILS = [
    "ada@example.com",
    "grace@example.com",
    "katherine@example.com",
    "marie@example.com",
    "radia@example.com",
]

PAGES = ["?limit=2", "?limit=2&offset=2", "?limit=2&offset=4"]
REFUSALS = ["?limit=abc", "?limit=0", "?limit=101", "?offset=-1"]


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            for email in EMAILS:
                client.post(
                    "/users", json={"email": email, "display_name": email.split("@")[0].title()}
                )

            for query in PAGES:
                response = client.get(f"/users{query}")
                page = response.json()
                emails = [item["email"] for item in page["items"]]
                print(f"GET /users{query} ->", response.status_code, emails, "of", page["total"])

            for query in REFUSALS:
                response = client.get(f"/users{query}")
                print(f"GET /users{query} ->", response.status_code, response.json()["error"])


if __name__ == "__main__":
    main()
