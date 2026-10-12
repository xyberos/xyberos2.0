"""Lesson 8 — identity from upstream, and the account it belongs to.

Run it with:

    python -m learn_traditional.traditional08_identity
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
SELF_CHANGES = [
    {"display_name": "Ada,   Countess of Lovelace "},
    {"enabled": False},
    {"external_subject": "linus@idp"},
    {"id": 2},
]


def show(label: str, response: Response) -> None:
    """Print one response as the lesson reads it: the status, then the body."""
    body = response.json() if response.content else None
    print(f"{label} ->", response.status_code, body)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        with create_test_client(HttpAdapter(create_app(settings=settings))) as unconfigured:
            show("no secret configured", unconfigured.get("/me"))

        app = create_app(settings=settings, secret=SECRET)
        verifier = PrincipalVerifier(SECRET)
        ada = verifier.headers("ada@idp")
        linus = verifier.headers("linus@idp")

        with create_test_client(HttpAdapter(app)) as client:
            show("unsigned", client.get("/me"))
            show(
                "signed for the wrong roles",
                client.get("/me", headers={**ada, "X-Authenticated-Roles": "admin"}),
            )
            show("before claiming an account", client.get("/me", headers=ada))

            show(
                "claim",
                client.post(
                    "/me",
                    json={"email": "Ada@Example.com", "display_name": "Ada Lovelace"},
                    headers=ada,
                ),
            )
            show("read back", client.get("/me", headers=ada))
            show("claim again", client.post("/me", json={"email": "a@b.com"}, headers=ada))

            for changes in SELF_CHANGES:
                show(f"PATCH /me {changes}", client.patch("/me", json=changes, headers=ada))

            show("somebody else", client.get("/me", headers=linus))


if __name__ == "__main__":
    main()
