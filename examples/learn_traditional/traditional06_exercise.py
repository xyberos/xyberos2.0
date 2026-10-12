"""Lesson 6, exercise — a full replacement, and how it differs from a partial edit.

The answer to the lesson's exercise. In your project the replacement goes into ``service.py`` and
the route into ``app.py``; it is a subclass here so the answer stays runnable without editing the
project.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

from httpx import Response
from starlette.requests import Request
from user_management.app import create_app
from user_management.errors import UserValidationError
from user_management.identity import PrincipalVerifier
from user_management.migrate import migrate
from user_management.service import ALLOWED_FIELDS, UserService

from xyberos import App, Inject
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter, read_json_object
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
#: The administrator's assertion, presented once and carried by every request.
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")

EMAILS = ["ada@example.com", "grace@example.com"]

REPLACEMENT = {"email": "ada@example.com", "display_name": "Ada Lovelace", "enabled": False}


class UserRegistry(UserService):
    """``service.py``, plus the replacement the exercise asks for."""

    async def replace_user(
        self, user_id: int, replacement: Mapping[str, object]
    ) -> dict[str, object]:
        """Replace every field of one user, or refuse a body that leaves one out."""
        _required_replacement(replacement)
        return await self.update_user(user_id, replacement)


def _required_replacement(replacement: Mapping[str, object]) -> None:
    """A replacement names every field, because one it leaves out would be dropped silently."""
    unknown = sorted(set(replacement) - set(ALLOWED_FIELDS))
    if unknown:
        raise UserValidationError(f"unknown field: {unknown[0]}")
    missing = [field for field in ALLOWED_FIELDS if field not in replacement]
    if missing:
        raise UserValidationError(f"a replacement needs {', '.join(ALLOWED_FIELDS)}")


def create_registry_app(*, settings: SqliteSettings) -> App:
    """The lesson's application, with the exercise's route added to it."""
    app = create_app(settings=settings, secret=SECRET)
    app.provide(UserRegistry)

    @app.put("/users/{user_id}")
    async def replace_user(
        user_id: int, request: Request, registry: Annotated[UserRegistry, Inject()]
    ) -> dict[str, object]:
        payload = await read_json_object(request)
        return await registry.replace_user(user_id, payload)

    return app


def show(label: str, response: Response) -> None:
    """Print one response as the lesson reads it: the status, then the body."""
    body = response.json() if response.content else None
    print(f"{label} ->", response.status_code, body)


def main() -> None:
    """Create two users, then replace one three ways, and edit one partially."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_registry_app(settings=settings)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            for email in EMAILS:
                client.post(
                    "/users", json={"email": email, "display_name": email.split("@")[0].title()}
                )

            show("PUT /users/1", client.put("/users/1", json=REPLACEMENT))
            show(
                "PUT /users/1 without enabled",
                client.put("/users/1", json={"email": "ada@example.com", "display_name": "Ada"}),
            )
            show("PUT /users/99", client.put("/users/99", json=REPLACEMENT))
            show(
                "PATCH /users/2",
                client.patch("/users/2", json={"display_name": "Rear Admiral Grace Hopper"}),
            )


if __name__ == "__main__":
    main()
