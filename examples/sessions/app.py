"""A session and CSRF recipe: log in once, then make a state-changing request survive the check.

Two middlewares, and the application owns both of them::

    SessionMiddleware(store=..., secret=...)   # remembers who signed in
    CSRFMiddleware()                           # refuses a state-changing request from another site

Neither is installed for you. ``HttpAdapter(app, middleware=(...))`` is the whole wiring, and the
app below is the shortest shape that is still correct:

- the **store** is an argument, so where the session lives — memory here, a table in production —
  is a deployment decision rather than a framework default;
- a handler writes to ``request.session`` and the middleware persists it **only if it changed**, so
  a page that merely reads the session costs no write and sets no cookie;
- the login itself is not the point. Identity and authorization stay absent
  ([ADR 0014](../../docs/adr/0014-no-identity-or-authorization-model.md)); a password check stands
  in for the verifier your proxy or identity provider already runs, and what arrives here is a
  principal you can trust because something upstream checked it.
"""

from __future__ import annotations

import hmac
import os

from starlette.middleware import Middleware
from starlette.requests import Request

from xyberos import App, HttpError, Settings
from xyberos.http import (
    CSRF_HEADER,
    CSRFMiddleware,
    HttpAdapter,
    InMemorySessionStore,
    SessionMiddleware,
    get_csrf_token,
    read_json_object,
)
from xyberos.http.testing import create_test_client

PASSWORDS = {"ada": "correct-horse"}
"""The directory this recipe stands in for. Real deployments verify an assertion, not a password."""


class UnauthenticatedError(HttpError):
    """The request needs a session, and there is none."""

    def __init__(self) -> None:
        super().__init__("sign in first", status_code=401)


def create_application(*, secret: str = "example-secret") -> HttpAdapter:
    """Compose the application: one store, two middlewares, and five routes.

    The one store is created here and handed to the middleware, because a store the adapter does not
    use is a store that remembers nothing.
    """
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "sessions"}}))
    store = InMemorySessionStore()

    @app.post("/login")
    async def login(request: Request) -> dict[str, str]:
        body = await read_json_object(request)
        user = str(body.get("user", ""))
        supplied = str(body.get("password", ""))
        expected = PASSWORDS.get(user, "")
        if not expected or not hmac.compare_digest(supplied, expected):
            raise UnauthenticatedError()
        request.session["user"] = user
        return {"user": user}

    @app.post("/logout")
    async def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"signed_out": True}

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | None]:
        return {"user": request.session.get("user")}

    @app.get("/order-form")
    async def order_form(request: Request) -> dict[str, str]:
        """A page that needs the token has one line to write."""
        return {"csrf_token": get_csrf_token(request)}

    @app.post("/orders")
    async def create_order(request: Request) -> dict[str, str]:
        user = request.session.get("user")
        if not user:
            raise UnauthenticatedError()
        body = await read_json_object(request)
        return {"ordered_by": str(user), "item": str(body.get("item", ""))}

    return HttpAdapter(
        app,
        middleware=(
            Middleware(SessionMiddleware, store=store, secret=secret),
            Middleware(CSRFMiddleware),
        ),
    )


def main() -> None:
    """Show the whole flow, including the one way it refuses, over the recipe's own adapter."""
    adapter = create_application(secret=os.environ.get("SESSION_SECRET", "example-secret"))

    with create_test_client(adapter) as client:
        client.post("/login", json={"user": "ada", "password": "correct-horse"})
        print("me:", client.get("/me").json())
        print("the cookie is not the data:", "ada" not in client.cookies.get("xyberos_session", ""))

        token = client.get("/order-form").json()["csrf_token"]
        same_origin = client.post(
            "/orders",
            json={"item": "printer paper"},
            headers={"Origin": "http://testserver", CSRF_HEADER: token},
        )
        print("same origin:", same_origin.status_code, same_origin.json()["item"])

        cross_site = client.post(
            "/orders",
            json={"item": "a new sofa"},
            headers={"Origin": "https://evil.example", CSRF_HEADER: token},
        )
        print("cross-site status:", cross_site.status_code)
        print("cross-site body:", cross_site.json()["error"]["type"])

        client.post("/logout")
        print("after logout:", client.get("/me").json())

        # A signed-out request to the protected route is refused before the body is read.
        print("signed out status:", client.post("/orders", json={"item": "x"}).status_code)


if __name__ == "__main__":
    main()
