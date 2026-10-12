"""Lesson 11, exercise — a rows fragment, for a list that refreshes itself.

The answer to the lesson's exercise. The fragment is the same `_row.html` the full page includes,
so there is one definition of a row and two ways to arrive at it: a browser asking for the page, and
HTMX asking for the table body it will swap in.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from starlette.requests import Request
from starlette.responses import Response
from starlette.templating import Jinja2Templates
from user_management.app import ADMIN, TEMPLATES, create_app
from user_management.identity import PrincipalVerifier, require_role
from user_management.migrate import migrate
from user_management.service import UserService

from xyberos import App, Inject
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", ADMIN)
EXERCISE_TEMPLATES = Path(__file__).parent / "templates"


def create_refreshing_app(*, settings: SqliteSettings) -> App:
    """The lesson's application, with the exercise's fragment route added to it."""
    app = create_app(settings=settings, secret=SECRET)
    templates = Jinja2Templates(directory=[str(TEMPLATES), str(EXERCISE_TEMPLATES)])

    @app.get("/pages/users/rows")
    async def user_rows(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> Response:
        """Return only the table's body: what a polling client swaps into the table."""
        require_role(verifier.verify(request), ADMIN)
        page = await users.list_users()
        return templates.TemplateResponse(request, "_rows.html", {"users": page["items"]})

    return app


def main() -> None:
    """Two clients, one definition of a row, and a fragment with no page in it."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_refreshing_app(settings=settings)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            client.post(
                "/pages/users",
                data={"email": "ada@example.com", "display_name": "Ada Lovelace"},
            )

            fragment = client.get("/pages/users/rows")
            print(
                "GET /pages/users/rows ->", fragment.status_code, fragment.headers["content-type"]
            )
            print("the fragment is a row:", fragment.text.count("<tr") == 1)
            print(
                "and nothing around it:",
                "<table" not in fragment.text,
                "<html" not in fragment.text,
            )
            print("the row is the page's row:", 'id="user-1"' in fragment.text)

            client.post(
                "/pages/users",
                data={"email": "grace@example.com", "display_name": "Grace Hopper"},
            )
            refreshed = client.get("/pages/users/rows").text
            print("after a write, the fragment has both rows:", refreshed.count("<tr") == 2)
            print("and the page agrees:", 'id="user-2"' in client.get("/pages/users").text)


if __name__ == "__main__":
    main()
