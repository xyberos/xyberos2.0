"""Lesson 9 — roles, and the difference between 401 and 403.

Run it with:

    python -m learn_traditional.traditional09_protected
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from httpx import Response
from user_management.app import create_app
from user_management.identity import PrincipalVerifier
from user_management.migrate import migrate

from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
VERIFIER = PrincipalVerifier(SECRET)
MEMBER = VERIFIER.headers("ada@idp", "member")
ADMIN = VERIFIER.headers("admin@idp", "admin")
#: A member's assertion with the roles header edited. The signature covers the roles, so it fails.
FORGED = {**MEMBER, "X-Authenticated-Roles": "admin"}


def show(label: str, response: Response) -> None:
    """Print one response as the lesson reads it: the status, then the body."""
    body = response.json() if response.content else None
    print(f"{label} ->", response.status_code, body)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            show("no assertion", client.get("/users"))
            show("a member asks for the collection", client.get("/users", headers=MEMBER))
            show("a member editing the roles header", client.get("/users", headers=FORGED))

            show(
                "an administrator creates a user",
                client.post(
                    "/users",
                    json={"email": "grace@example.com", "display_name": "Grace Hopper"},
                    headers=ADMIN,
                ),
            )
            listed = client.get("/users", headers=ADMIN)
            print(
                "an administrator sees", len(listed.json()["items"]), "of", listed.json()["total"]
            )

            show(
                "a member claims an account",
                client.post(
                    "/me",
                    json={"email": "ada@example.com", "display_name": "Ada Lovelace"},
                    headers=MEMBER,
                ),
            )
            show("a member reads their own account", client.get("/me", headers=MEMBER))
            show("a member reads the admin's account", client.get("/users/1", headers=MEMBER))


if __name__ == "__main__":
    main()
