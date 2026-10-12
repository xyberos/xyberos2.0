"""Lesson 6 — reading one user, editing one, and deleting one.

Run it with:

    python -m learn_traditional.traditional06_crud
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
#: The administrator's assertion, presented once and carried by every request.
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")

EMAILS = ["ada@example.com", "grace@example.com", "katherine@example.com"]

CHANGES = [
    (1, {"display_name": "  Ada,   Countess of Lovelace "}),
    (1, {"enabled": "yes"}),
    (1, {"nickname": "Ada"}),
    (1, {"email": "ada@example.com"}),
    (2, {"email": "ada@example.com"}),
]


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
            client.headers.update(ADMIN_HEADERS)
            for email in EMAILS:
                client.post(
                    "/users", json={"email": email, "display_name": email.split("@")[0].title()}
                )

            show("GET /users/1", client.get("/users/1"))
            show("GET /users/99", client.get("/users/99"))
            show("GET /users/abc", client.get("/users/abc"))

            for user_id, changes in CHANGES:
                show(
                    f"PATCH /users/{user_id} {changes}",
                    client.patch(f"/users/{user_id}", json=changes),
                )

            show("DELETE /users/3", client.delete("/users/3"))
            show("DELETE /users/3 again", client.delete("/users/3"))

            listing = client.get("/users").json()
            print(
                "GET /users ->",
                [item["email"] for item in listing["items"]],
                "of",
                listing["total"],
            )


if __name__ == "__main__":
    main()
