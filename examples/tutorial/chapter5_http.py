"""Chapter 5 — an application that answers HTTP.

Run it with:

    python examples/tutorial/chapter5_http.py

The test client below is the same client the test suite uses, so you can follow along without
starting a server. `docs/tutorial.md` shows the server command as well.
"""

from __future__ import annotations

from typing import Annotated

from starlette.applications import Starlette

from xyberos import App, Inject
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


class Greeter:
    """The service the first route uses."""

    def greet(self, name: str) -> str:
        """Return a greeting."""
        return f"Hello, {name}!"


def create_app() -> App:
    """Build the application: services first, then routes."""
    app = App()
    app.provide(Greeter)

    @app.get("/")
    async def hello(greeter: Annotated[Greeter, Inject()]) -> dict[str, str]:
        return {"message": greeter.greet("world")}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def build_asgi_app(app: App) -> Starlette:
    """Build the ASGI application an ASGI server can run."""
    return HttpAdapter(app).asgi_app


def app_factory() -> Starlette:
    """Build the example ASGI application for an ASGI server.

    Usage: ``uvicorn --app-dir examples/tutorial --factory chapter5_http:app_factory``
    """
    return build_asgi_app(create_app())


def main() -> None:
    with create_test_client(HttpAdapter(create_app())) as client:
        response = client.get("/")
        print("status:", response.status_code)
        print("json:", response.json())
        print("health:", client.get("/health").json())
        print("correlation id set:", bool(response.headers.get("X-Request-ID")))


if __name__ == "__main__":
    main()
