"""Lesson 4 — creating and listing users through the application's own routes.

Run it with:

    python -m learn_traditional.traditional04_users
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

USERS = [
    {"email": "  ADA@Example.com ", "display_name": "Ada   Lovelace"},
    {"email": "ada@example.com", "display_name": "Ada Again"},
    {"email": "not-an-email", "display_name": "Nobody"},
    {"email": "grace@example.com", "display_name": "Grace Hopper"},
]


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            print("health:", client.get("/health").json())

            for payload in USERS:
                response = client.post("/users", json=payload)
                print("POST /users ->", response.status_code, response.json())

            listing = client.get("/users")
            print("GET /users ->", listing.status_code)
            print(listing.json())


if __name__ == "__main__":
    main()
