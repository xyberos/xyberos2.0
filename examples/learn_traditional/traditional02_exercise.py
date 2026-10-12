"""Lesson 2, exercise — say no with the right status code.

The answer to the lesson's exercise: creating the same item twice is a conflict, and the status code
says so without the handler thinking about HTTP beyond the number.
"""

from __future__ import annotations

from starlette.requests import Request

from xyberos import App, HttpError
from xyberos.http import HttpAdapter, read_json_object
from xyberos.http.testing import create_test_client


class ItemAlreadyExistsError(HttpError):
    """A domain error that knows which HTTP status it means."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name!r} already exists", status_code=409)


def create_app() -> App:
    """Build the application, with the store created per application rather than per module."""
    items = {1: "notebook"}
    app = App()

    @app.post("/items")
    async def create_item(request: Request) -> dict[str, object]:
        payload = await read_json_object(request)
        name = str(payload.get("name"))
        if name in items.values():
            raise ItemAlreadyExistsError(name)
        item_id = max(items) + 1
        items[item_id] = name
        return {"created": name, "id": item_id}

    return app


def main() -> None:
    """Create one item, then try to create it again."""
    with create_test_client(HttpAdapter(create_app())) as client:
        print("created:", client.post("/items", json={"name": "pen"}).json())

        conflict = client.post("/items", json={"name": "pen"})
        print("conflict status:", conflict.status_code)
        print("conflict type:", conflict.json()["error"]["type"])


if __name__ == "__main__":
    main()
