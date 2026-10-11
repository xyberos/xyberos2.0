"""Chapter 6 — reading a request, and saying no to one.

Run it with:

    python examples/tutorial/chapter6_requests_and_errors.py
"""

from __future__ import annotations

from starlette.requests import Request

from xyberos import App, HttpError
from xyberos.http import HttpAdapter, read_json_object
from xyberos.http.testing import create_test_client

ITEMS = {1: "notebook"}


class ItemNotFoundError(HttpError):
    """A domain error that knows which HTTP status it means."""

    def __init__(self, item_id: int) -> None:
        super().__init__(f"item {item_id} was not found", status_code=404)


def create_app() -> App:
    """Build the application."""
    app = App()

    @app.get("/items/{item_id}")
    async def get_item(item_id: int) -> dict[str, object]:
        if item_id not in ITEMS:
            raise ItemNotFoundError(item_id)
        return {"item_id": item_id, "name": ITEMS[item_id]}

    @app.get("/search")
    async def search(request: Request) -> dict[str, str]:
        return {"query": request.query_params.get("q", "all")}

    @app.post("/items")
    async def create_item(request: Request) -> dict[str, object]:
        payload = await read_json_object(request)
        return {"created": payload.get("name"), "id": max(ITEMS) + 1}

    return app


def main() -> None:
    with create_test_client(HttpAdapter(create_app())) as client:
        print("found:", client.get("/items/1").json())
        print("query:", client.get("/search?q=book").json())

        missing = client.get("/items/99")
        print("missing status:", missing.status_code)
        print("missing body:", missing.json())

        print("created:", client.post("/items", json={"name": "pen"}).json())

        broken = client.post("/items", content=b"this is not json")
        print("broken body status:", broken.status_code)
        print("broken body type:", broken.json()["error"]["type"])


if __name__ == "__main__":
    main()
