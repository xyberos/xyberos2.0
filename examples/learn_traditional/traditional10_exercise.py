"""Lesson 10, exercise — an edit form over the same service and the same rules.

The answer to the lesson's exercise. In your project the two routes go into ``app.py`` and the
template into ``templates/``; the answer adds its own template directory here so it stays runnable
without editing the project.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.templating import Jinja2Templates
from user_management.app import ADMIN, TEMPLATES, create_app
from user_management.errors import UserValidationError
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


def create_edit_app(*, settings: SqliteSettings) -> App:
    """The lesson's application, with the exercise's two routes added to it."""
    app = create_app(settings=settings, secret=SECRET)
    templates = Jinja2Templates(directory=[str(TEMPLATES), str(EXERCISE_TEMPLATES)])

    async def render(
        request: Request,
        users: UserService,
        user_id: int,
        *,
        status_code: int = 200,
        error: str | None = None,
    ) -> Response:
        """Render the form for one user, with what was typed if a submission was refused."""
        user = await users.get_user(user_id)
        form = None
        if request.method == "POST":
            submitted = await request.form()
            form = {key: str(value) for key, value in submitted.items()}
        return templates.TemplateResponse(
            request,
            "edit.html",
            {"user": user, "error": error, "form": form},
            status_code=status_code,
        )

    @app.get("/pages/users/{user_id}/edit")
    async def edit_form(
        user_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> Response:
        require_role(verifier.verify(request), ADMIN)
        return await render(request, users, user_id)

    @app.post("/pages/users/{user_id}/edit")
    async def save_edit(
        user_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> Response:
        require_role(verifier.verify(request), ADMIN)
        submitted = await request.form()
        try:
            await users.update_user(user_id, {"display_name": submitted.get("display_name")})
        except UserValidationError as error:
            return await render(request, users, user_id, status_code=422, error=str(error))
        return RedirectResponse("/pages/users", status_code=303)

    return app


def main() -> None:
    """Read a form, save it, refuse a bad one, and let a missing user stay a 404."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_edit_app(settings=settings)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            client.post(
                "/pages/users",
                data={"email": "grace@example.com", "display_name": "Grace Hopper"},
            )

            form = client.get("/pages/users/1/edit")
            print(
                "GET the edit form ->", form.status_code, "prefilled:", "Grace Hopper" in form.text
            )

            saved = client.post(
                "/pages/users/1/edit",
                data={"display_name": "  Rear Admiral   Grace Hopper "},
                follow_redirects=False,
            )
            print("POST the edit ->", saved.status_code, saved.headers["location"])
            print(
                "the list shows the new name:",
                "Rear Admiral Grace Hopper" in client.get("/pages/users").text,
            )

            refused = client.post(
                "/pages/users/1/edit", data={"display_name": "   "}, follow_redirects=False
            )
            print("POST an empty name ->", refused.status_code)
            print("and says why:", "display_name must be a non-empty string" in refused.text)

            missing = client.get("/pages/users/99/edit")
            print("GET a form for a missing user ->", missing.status_code)


if __name__ == "__main__":
    main()
