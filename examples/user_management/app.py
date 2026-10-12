"""Compose the application and expose it as an ASGI app."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

from starlette.applications import Starlette
from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.templating import Jinja2Templates

from user_management.errors import DuplicateEmailError, UserValidationError
from user_management.identity import PrincipalVerifier, require_role
from user_management.service import DEFAULT_LIMIT, UserService
from xyberos import App, Inject, Settings
from xyberos.database import DatabaseProvider, SqliteSettings, sqlite_provider
from xyberos.http import HttpAdapter, read_json_object

#: The role the administrative routes require. One constant, so the route table reads as a list.
ADMIN = "admin"

#: Where the pages live. Templates are application code: the framework routes and serializes, and a
#: template engine is something an application adds.
TEMPLATES = Path(__file__).parent / "templates"

#: The header HTMX sends. It is how one route answers a browser and a script differently.
HX_REQUEST = "HX-Request"


def create_app(
    *,
    settings: SqliteSettings | None = None,
    database: DatabaseProvider | None = None,
    secret: str | None = None,
) -> App:
    """Compose the application.

    Pass ``settings`` to let the application own and start its database, or ``database`` to supply
    an already-started provider, which the application then owns and closes on shutdown. ``secret``
    is the identity provider's shared secret; without one the verifier refuses every request.
    """
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "user_management"}}))
    if database is None:
        app.provide(DatabaseProvider, factory=sqlite_provider(settings), eager=True)
    else:
        app.provide(DatabaseProvider, instance=database)
    app.provide(UserService)
    app.provide(PrincipalVerifier, instance=PrincipalVerifier(secret))

    def administrator(request: Request, verifier: PrincipalVerifier) -> None:
        """Refuse a caller who is not an administrator, before anything else happens.

        One call at the top of a route, and its cost is that it can be forgotten: there is no marker
        on the handler that a reviewer can grep for except this line. That is the trade the ADR
        describes — the application owns authorization, so the route table is where it is audited.
        """
        require_role(verifier.verify(request), ADMIN)

    @app.get("/health")
    async def health(database: Annotated[DatabaseProvider, Inject()]) -> dict[str, str]:
        await database.health()
        return {"status": "ready"}

    @app.post("/users")
    async def create_user(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> dict[str, object]:
        administrator(request, verifier)
        payload = await read_json_object(request)
        return await users.create_user(payload.get("email"), payload.get("display_name"))

    @app.get("/users")
    async def list_users(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> dict[str, object]:
        administrator(request, verifier)
        query = request.query_params
        return await users.list_users(
            limit=_whole_number(query, "limit", default=DEFAULT_LIMIT),
            offset=_whole_number(query, "offset", default=0),
        )

    @app.get("/users/{user_id}")
    async def get_user(
        user_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> dict[str, object]:
        administrator(request, verifier)
        return await users.get_user(user_id)

    @app.patch("/users/{user_id}")
    async def update_user(
        user_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> dict[str, object]:
        administrator(request, verifier)
        payload = await read_json_object(request)
        return await users.update_user(user_id, payload)

    @app.delete("/users/{user_id}")
    async def delete_user(
        user_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> None:
        administrator(request, verifier)
        await users.delete_user(user_id)

    @app.get("/me")
    async def read_me(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        return await users.find_own_user(principal)

    @app.post("/me")
    async def claim_account(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        payload = await read_json_object(request)
        return await users.create_user(
            payload.get("email"),
            payload.get("display_name"),
            external_subject=principal.subject,
        )

    @app.patch("/me")
    async def update_me(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        payload = await read_json_object(request)
        return await users.update_own_profile(principal, payload)

    templates = Jinja2Templates(directory=str(TEMPLATES))

    async def users_page(
        request: Request, users: UserService, *, status_code: int = 200, error: str | None = None
    ) -> Response:
        page = await users.list_users()
        return templates.TemplateResponse(
            request,
            "users.html",
            {"users": page["items"], "error": error, "form": await _submitted_form(request)},
            status_code=status_code,
        )

    @app.get("/pages/users")
    async def show_users(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> Response:
        administrator(request, verifier)
        return await users_page(request, users)

    @app.post("/pages/users")
    async def create_user_from_form(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> Response:
        administrator(request, verifier)
        form = await request.form()
        try:
            await users.create_user(form.get("email"), form.get("display_name"))
        except (DuplicateEmailError, UserValidationError) as error:
            return await users_page(request, users, status_code=422, error=str(error))
        return RedirectResponse("/pages/users", status_code=303)

    @app.post("/pages/users/{user_id}/toggle")
    async def toggle_user(
        user_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        users: Annotated[UserService, Inject()],
    ) -> Response:
        administrator(request, verifier)
        current = await users.get_user(user_id)
        updated = await users.update_user(user_id, {"enabled": not current["enabled"]})
        if request.headers.get(HX_REQUEST):
            return templates.TemplateResponse(request, "_row.html", {"user": updated})
        return RedirectResponse("/pages/users", status_code=303)

    return app


async def _submitted_form(request: Request) -> Mapping[str, object] | None:
    """Return what the client typed, so a refused form can be shown back to them."""
    if request.method != "POST":
        return None
    form = await request.form()
    return {key: str(value) for key, value in form.items()}


def _whole_number(query: QueryParams, name: str, *, default: int) -> int:
    """Read one query string value as a whole number, or refuse the request.

    A query string is text: `?limit=abc` arrives as `"abc"`. The conversion belongs here, where the
    request is untrusted, and the *bounds* stay in the service, which knows what a page may be.
    """
    raw = query.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise UserValidationError(f"{name} must be a whole number") from None


def build_asgi_app(app: App) -> Starlette:
    """Build an ASGI application for a composed application."""
    return HttpAdapter(app).asgi_app


def app_factory() -> Starlette:
    """Create the application's ASGI app for an ASGI server.

    The identity secret is read from the environment by the verifier, and a deployment that has not
    set it refuses every request rather than trusting one.

    Usage: ``uvicorn --app-dir examples --factory user_management.app:app_factory``
    """
    return build_asgi_app(create_app())
