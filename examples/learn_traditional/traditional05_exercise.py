"""Lesson 5, exercise — an exact-match email filter that pages like any other collection.

The answer to the lesson's exercise. In your project this is one more argument on `list_users` and
one more branch in the same handler. It is a separate route here, on `/directory` rather than under
`/users/`, so the answer stays runnable while the project keeps changing underneath it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from httpx import Response
from sqlalchemy import func, select
from starlette.requests import Request
from user_management.app import create_app
from user_management.errors import UserValidationError
from user_management.identity import PrincipalVerifier
from user_management.migrate import migrate
from user_management.service import DEFAULT_LIMIT, UserService
from user_management.tables import users

from xyberos import App, Inject
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
#: The administrator's assertion, presented once and carried by every request.
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")

EMAILS = ["ada@example.com", "grace@example.com", "katherine@example.com"]

FILTERS = ["", "?email=ADA@example.com", "?email=marie@example.com", "?email="]


class UserDirectory(UserService):
    """``service.py``, plus the one query the exercise asks for."""

    async def find_users(
        self, email: object, *, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> dict[str, object]:
        """Return one page of users with exactly this address, and how many there are."""
        wanted = _required_email(email)
        page = select(users).where(users.c.email == wanted).order_by(users.c.id)
        count = select(func.count()).select_from(users).where(users.c.email == wanted)
        async with self._database.transaction() as connection:
            total = int((await connection.execute(count)).scalar_one())
            rows = (await connection.execute(page.limit(limit).offset(offset))).mappings().all()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def _required_email(email: object) -> str:
    """Normalise the filter the way `create_user` normalises the value it stores."""
    if not isinstance(email, str) or not email.strip():
        raise UserValidationError("email must not be blank")
    return email.strip().lower()


def create_directory_app(*, settings: SqliteSettings) -> App:
    """The lesson's application, with the exercise's route added to it."""
    app = create_app(settings=settings, secret=SECRET)
    app.provide(UserDirectory)

    @app.get("/directory")
    async def find_users(
        request: Request,
        users: Annotated[UserService, Inject()],
        directory: Annotated[UserDirectory, Inject()],
    ) -> dict[str, object]:
        email = request.query_params.get("email")
        if email is None:
            return await users.list_users()
        return await directory.find_users(email)

    return app


def report(query: str, response: Response) -> None:
    """Print one response: the addresses it matched, or the refusal it returned."""
    body = response.json()
    if response.status_code == 200:
        addresses = [item["email"] for item in body["items"]]
        print(f"GET /directory{query} ->", response.status_code, addresses, "of", body["total"])
    else:
        print(f"GET /directory{query} ->", response.status_code, body["error"]["message"])


def main() -> None:
    """Create three users, then filter the collection four ways."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_directory_app(settings=settings)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            for email in EMAILS:
                client.post(
                    "/users", json={"email": email, "display_name": email.split("@")[0].title()}
                )

            for query in FILTERS:
                report(query, client.get(f"/directory{query}"))


if __name__ == "__main__":
    main()
