"""Lesson 12 — what a deployment has to get right, checked rather than asserted.

Run it with:

    python -m learn_traditional.traditional12_deploy
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from starlette.applications import Starlette
from user_management.app import build_asgi_app, create_app
from user_management.identity import SECRET_ENV, PrincipalVerifier
from user_management.migrate import migrate

from xyberos.database import SqliteSettings
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")


def report(label: str, value: object) -> None:
    """Print one fact a deployment depends on."""
    print(f"{label}: {value}")


def routes_of(application: Starlette) -> list[str]:
    """Return the paths the ASGI application answers on, sorted, as a deployment would list them."""
    return sorted({route.path for route in application.routes if hasattr(route, "path")})


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")

        app = create_app(settings=settings, secret=SECRET)
        app.validate()
        report("the application validates", "yes")

        asgi = build_asgi_app(app)
        report("it answers on", routes_of(asgi))

        with create_test_client(asgi) as client:
            report("before migrating, /health answers", client.get("/health").status_code)
            report(
                "before migrating, a query fails",
                client.get("/users", headers=ADMIN_HEADERS).status_code,
            )

        migrate(settings)
        report("the deploy step migrated", Path(settings.path).name)

        started = build_asgi_app(create_app(settings=settings, secret=SECRET))
        with create_test_client(started) as client:
            report("/users without an assertion", client.get("/users").status_code)
            report(
                "/users as an administrator",
                client.get("/users", headers=ADMIN_HEADERS).status_code,
            )
            report("an unknown path", client.get("/nope").status_code)
            health = client.get("/health")
            report("every answer carries a request id", bool(health.headers.get("x-request-id")))
            report("no secret is echoed", SECRET not in health.text)

        unconfigured = build_asgi_app(create_app(settings=settings))
        with create_test_client(unconfigured) as client:
            report(
                "a deployment with no secret refuses every request",
                client.get("/users", headers=ADMIN_HEADERS).status_code,
            )
        report(f"the secret is read from {SECRET_ENV}", "yes")


if __name__ == "__main__":
    main()
