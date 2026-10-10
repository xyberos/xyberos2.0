"""Compose the example application and expose it as an ASGI app."""

from __future__ import annotations

from typing import Annotated

from starlette.applications import Starlette
from starlette.requests import Request

from sqlite_crud.errors import ItemValidationError
from sqlite_crud.service import ItemService
from xyberos import App, Inject, Settings
from xyberos.database import DatabaseProvider, SqliteSettings, sqlite_provider
from xyberos.http import HttpAdapter, read_json_object


def create_app(
    *,
    settings: SqliteSettings | None = None,
    database: DatabaseProvider | None = None,
) -> App:
    """Compose the application.

    Pass ``settings`` to let the application own and start its database, or ``database`` to supply
    an already-started provider, which the application then owns and closes on shutdown.
    """
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "sqlite_crud"}}))
    if database is None:
        app.provide(DatabaseProvider, factory=sqlite_provider(settings), eager=True)
    else:
        app.provide(DatabaseProvider, instance=database)
    app.provide(ItemService)

    @app.get("/health")
    async def health(database: Annotated[DatabaseProvider, Inject()]) -> dict[str, str]:
        await database.health()
        return {"status": "ready"}

    @app.get("/items")
    async def list_items(items: Annotated[ItemService, Inject()]) -> list[dict[str, object]]:
        return await items.list_items()

    @app.get("/items/{item_id}")
    async def get_item(item_id: int, items: Annotated[ItemService, Inject()]) -> dict[str, object]:
        return await items.get_item(item_id)

    @app.post("/items")
    async def create_item(
        request: Request, items: Annotated[ItemService, Inject()]
    ) -> dict[str, object]:
        payload = await read_json_object(request)
        return await items.create_item(payload.get("name"))

    @app.patch("/items/{item_id}")
    async def update_item(
        item_id: int, request: Request, items: Annotated[ItemService, Inject()]
    ) -> dict[str, object]:
        payload = await read_json_object(request)
        if "name" in payload:
            return await items.rename_item(item_id, payload["name"])
        if "completed" in payload:
            return await items.set_completed(item_id, payload["completed"])
        raise ItemValidationError("provide name or completed")

    @app.delete("/items/{item_id}")
    async def delete_item(item_id: int, items: Annotated[ItemService, Inject()]) -> None:
        await items.delete_item(item_id)

    return app


def build_asgi_app(app: App) -> Starlette:
    """Build an ASGI application for a composed example application."""
    return HttpAdapter(app).asgi_app


def app_factory() -> Starlette:
    """Create the example ASGI application for an ASGI server.

    Usage: ``uvicorn --app-dir examples --factory sqlite_crud.app:app_factory``
    """
    return build_asgi_app(create_app())
