from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from xyberos.http.middleware import IdentityResolver, XyberosContextMiddleware
from xyberos.kernel import ExecutionContextAccessor, XyberosKernel
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.database import Database, DatabaseSubsystem


async def list_items(request: Request) -> JSONResponse:
    context = ExecutionContextAccessor.get()
    database = request.app.state.kernel.container.resolve(Database)
    rows = await database.fetch_all(
        "SELECT id, title FROM items WHERE tenant_id = ? ORDER BY title, id",
        (context.tenant_id,),
    )
    return JSONResponse({"items": rows})


async def create_item(request: Request) -> JSONResponse:
    context = ExecutionContextAccessor.get()
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"detail": "Request body must be valid JSON."}, status_code=400)
    if not isinstance(body, dict) or not isinstance(body.get("title"), str):
        return JSONResponse({"detail": "'title' must be a string."}, status_code=400)
    title = body["title"].strip()
    if not title:
        return JSONResponse({"detail": "'title' must not be empty."}, status_code=400)

    database = request.app.state.kernel.container.resolve(Database)
    item = {"id": str(uuid4()), "title": title}
    await database.execute(
        "INSERT INTO items (id, tenant_id, title) VALUES (?, ?, ?)",
        (item["id"], context.tenant_id, item["title"]),
    )
    return JSONResponse(item, status_code=201)


async def get_item(request: Request) -> JSONResponse:
    context = ExecutionContextAccessor.get()
    database = request.app.state.kernel.container.resolve(Database)
    item = await database.fetch_one(
        "SELECT id, title FROM items WHERE id = ? AND tenant_id = ?",
        (request.path_params["item_id"], context.tenant_id),
    )
    if item is None:
        return JSONResponse({"detail": "Item not found."}, status_code=404)
    return JSONResponse(item)


async def delete_item(request: Request) -> Response:
    context = ExecutionContextAccessor.get()
    database = request.app.state.kernel.container.resolve(Database)
    result = await database.execute(
        "DELETE FROM items WHERE id = ? AND tenant_id = ?",
        (request.path_params["item_id"], context.tenant_id),
    )
    if result.rowcount == 0:
        return JSONResponse({"detail": "Item not found."}, status_code=404)
    return Response(status_code=204)


def create_app(
    identity_resolver: IdentityResolver | None = None,
    database_path: str = "./data/example.db",
) -> Starlette:
    provider = SQLiteProvider()
    database_subsystem = DatabaseSubsystem(provider)
    kernel = XyberosKernel(
        {
            "xyberos": {
                "subsystems": {
                    "database": {
                        "enabled": True,
                        "provider": provider.provider_name,
                        "config": {
                            "path": database_path,
                            "journal_mode": "WAL",
                            "busy_timeout_ms": 30_000,
                        },
                    }
                }
            }
        }
    )
    kernel.register_provider("database", provider)
    kernel.register_subsystem("database", database_subsystem)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.ready = False
        await kernel.bootstrap()
        try:
            database = kernel.container.resolve(Database)
            await database.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    title TEXT NOT NULL
                )
                """
            )
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            await kernel.shutdown()

    app = Starlette(
        routes=[
            Route("/items", list_items, methods=["GET"]),
            Route("/items", create_item, methods=["POST"]),
            Route("/items/{item_id}", get_item, methods=["GET"]),
            Route("/items/{item_id}", delete_item, methods=["DELETE"]),
        ],
        lifespan=lifespan,
    )
    app.state.kernel = kernel
    app.add_middleware(
        XyberosContextMiddleware,
        identity_resolver=identity_resolver,
    )
    return app


app = create_app()
