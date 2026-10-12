"""Lesson 8, exercise — a verifier replaced by a fixed principal, for a test.

The answer to the lesson's exercise. `app.with_overrides` swaps the verifier for one that answers
from a constant, which is what a test wants: the subject is the thing under test's control, and no
signature has to be computed to express it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from starlette.requests import Request
from user_management.app import create_app
from user_management.identity import Principal, PrincipalVerifier
from user_management.migrate import migrate

from xyberos import App
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


class FixedVerifier(PrincipalVerifier):
    """The test double: no signing, no secret, one principal."""

    def __init__(self, subject: str) -> None:
        super().__init__("the-secret-is-irrelevant-for-a-fixed-principal")
        self._subject = subject

    def verify(self, request: Request) -> Principal:
        """Answer with the same principal for every request."""
        return Principal(subject=self._subject, roles=frozenset({"member"}))


def app_with_fixed_principal(*, settings: SqliteSettings, subject: str) -> App:
    """The application under test, with the verifier it would use in production replaced."""
    app = create_app(settings=settings, secret="unused")
    return app.with_overrides({PrincipalVerifier: FixedVerifier(subject)})


def main() -> None:
    """Claim and read an account without a single assertion header."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = app_with_fixed_principal(settings=settings, subject="ada@idp")
        with create_test_client(HttpAdapter(app)) as client:
            claimed = client.post(
                "/me",
                json={"email": "ada@example.com", "display_name": "Ada Lovelace"},
            )
            print(
                "claimed with no headers:", claimed.status_code, claimed.json()["external_subject"]
            )
            shown = client.get("/me")
            print("read with no headers:", shown.status_code, shown.json()["email"])


if __name__ == "__main__":
    main()
