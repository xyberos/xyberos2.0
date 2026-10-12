"""Lesson 4, exercise — deactivate a user, and the 404 when there is no such user.

The answer to the lesson's exercise. In your project the `set_enabled` method goes into
``service.py`` and the route into ``app.py``; they are a subclass here so the answer stays runnable.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from sqlalchemy import select, update
from user_management.app import create_app
from user_management.errors import UserNotFoundError
from user_management.identity import PrincipalVerifier
from user_management.migrate import migrate
from user_management.service import UserService
from user_management.tables import users

from xyberos import App, Inject
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
#: The administrator's assertion, presented once and carried by every request.
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")


class UserAdmin(UserService):
    """``service.py``, plus the one write the exercise asks for."""

    async def set_enabled(self, user_id: int, enabled: bool) -> dict[str, object]:
        """Enable or disable one user, or raise because there is no such user."""
        async with self._database.transaction() as connection:
            result = await connection.execute(
                update(users).where(users.c.id == user_id).values(enabled=enabled)
            )
            if result.rowcount == 0:
                raise UserNotFoundError(user_id)
            row = (
                (await connection.execute(select(users).where(users.c.id == user_id)))
                .mappings()
                .one()
            )
        return dict(row)


def create_admin_app(*, settings: SqliteSettings) -> App:
    """The lesson's application, with the exercise's route added to it."""
    app = create_app(settings=settings, secret=SECRET)
    app.provide(UserAdmin)

    @app.post("/users/{user_id}/deactivate")
    async def deactivate(user_id: int, admin: Annotated[UserAdmin, Inject()]) -> dict[str, object]:
        return await admin.set_enabled(user_id, enabled=False)

    return app


def main() -> None:
    """Create one user, deactivate it, then deactivate a user that does not exist."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_admin_app(settings=settings)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            created = client.post(
                "/users", json={"email": "ada@example.com", "display_name": "Ada Lovelace"}
            )
            print("created:", created.status_code, created.json())

            deactivated = client.post("/users/1/deactivate")
            print("deactivated:", deactivated.status_code, deactivated.json())

            missing = client.post("/users/99/deactivate")
            print("missing:", missing.status_code, missing.json())


if __name__ == "__main__":
    main()
