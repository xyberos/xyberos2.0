"""Lesson 1, exercise — a route that greets whoever is in the URL.

The answer to the lesson's exercise. The only new idea is a path parameter: it is a handler argument
whose name appears in the route, and the adapter converts it to the declared type.
"""

from __future__ import annotations

from typing import Annotated

from xyberos import App, Inject
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


class Greeter:
    """The service the route uses."""

    def greet(self, name: str) -> str:
        """Return a greeting."""
        return f"Hello, {name}!"


def create_app() -> App:
    """Build the application with one route that takes a path parameter."""
    app = App()
    app.provide(Greeter)

    @app.get("/hello/{name}")
    async def hello_name(name: str, greeter: Annotated[Greeter, Inject()]) -> dict[str, str]:
        return {"message": greeter.greet(name)}

    return app


def main() -> None:
    """Ask the route for a greeting."""
    with create_test_client(HttpAdapter(create_app())) as client:
        print(client.get("/hello/Ada").json())


if __name__ == "__main__":
    main()
