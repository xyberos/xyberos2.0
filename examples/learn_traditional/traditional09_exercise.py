"""Lesson 9, exercise — owner or administrator, and no third case.

The answer to the lesson's exercise. The check is the one every application eventually writes: a
caller may read their own record, and an administrator may read anybody's, and everybody else is
refused with the same `403` — the same message, so the refusal does not become a way to enumerate
which accounts exist.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from httpx import Response
from starlette.requests import Request
from user_management.app import ADMIN, create_app
from user_management.identity import ForbiddenError, Principal, PrincipalVerifier
from user_management.migrate import migrate
from user_management.service import UserService

from xyberos import App, Inject
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
VERIFIER = PrincipalVerifier(SECRET)
MEMBER = VERIFIER.headers("ada@idp", "member")
ADMIN_HEADERS = VERIFIER.headers("admin@idp", ADMIN)


class UserReader(UserService):
    """``service.py``, plus the one authorization rule the exercise asks for."""

    async def read_for(self, principal: Principal, user_id: int) -> dict[str, object]:
        """Return one user, if the caller owns that account or administers the application."""
        if ADMIN not in principal.roles:
            own = await self.find_own_user(principal)
            if own["id"] != user_id:
                raise ForbiddenError(f"the {ADMIN} role or your own account")
        return await self.get_user(user_id)


def create_guarded_app(*, settings: SqliteSettings) -> App:
    """The lesson's application, with the exercise's route added to it."""
    app = create_app(settings=settings, secret=SECRET)
    app.provide(UserReader)

    @app.get("/accounts/{user_id}")
    async def read_account(
        user_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        reader: Annotated[UserReader, Inject()],
    ) -> dict[str, object]:
        return await reader.read_for(verifier.verify(request), user_id)

    return app


def show(label: str, response: Response) -> None:
    """Print one response as the lesson reads it: the status, then the body."""
    body = response.json() if response.content else None
    print(f"{label} ->", response.status_code, body)


def main() -> None:
    """One member, one administrator, and the three answers the rule can give."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_guarded_app(settings=settings)
        with create_test_client(HttpAdapter(app)) as client:
            claimed = client.post(
                "/me",
                json={"email": "ada@example.com", "display_name": "Ada Lovelace"},
                headers=MEMBER,
            )
            print("the member's own id:", claimed.json()["id"])

            show("their own account", client.get("/accounts/1", headers=MEMBER))
            show("somebody else's account", client.get("/accounts/99", headers=MEMBER))
            show(
                "an administrator reads account 99",
                client.get("/accounts/99", headers=ADMIN_HEADERS),
            )
            show(
                "an administrator reads account 1", client.get("/accounts/1", headers=ADMIN_HEADERS)
            )


if __name__ == "__main__":
    main()
