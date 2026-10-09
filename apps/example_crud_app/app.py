from __future__ import annotations

import json
from contextlib import asynccontextmanager
from collections.abc import Mapping
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from xyberos.http.health import create_health_routes
from xyberos.http.middleware import (
    IdentityResolver,
    KernelAdmissionMiddleware,
    XyberosContextMiddleware,
)
from xyberos.kernel import (
    ExecutionContextAccessor,
    PolicyEngine,
    XyberosKernel,
)
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.ai import AISubsystem, ModelMessage, ModelProvider
from xyberos.subsystems.ai.contracts import ModelResponse
from xyberos.subsystems.database import (
    Database,
    DatabaseSubsystem,
    SchemaMigration,
    SchemaMigrator,
)

_SCHEMA_MIGRATIONS = (
    SchemaMigration(
        version=1,
        statements=(
            """
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                title TEXT NOT NULL
            )
            """,
        ),
    ),
)


async def migrate_schema(database: Database) -> tuple[int, ...]:
    return await SchemaMigrator(database).apply(_SCHEMA_MIGRATIONS)


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


async def generate_text(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"detail": "Request body must be valid JSON."}, status_code=400)
    if not isinstance(body, dict) or not isinstance(body.get("prompt"), str):
        return JSONResponse({"detail": "'prompt' must be a string."}, status_code=400)
    prompt = body["prompt"].strip()
    if not prompt:
        return JSONResponse({"detail": "'prompt' must not be empty."}, status_code=400)
    if len(prompt) > 100_000:
        return JSONResponse(
            {"detail": "'prompt' exceeds the 100000 character limit."},
            status_code=400,
        )

    model_provider = request.app.state.kernel.container.resolve(ModelProvider)
    try:
        result: ModelResponse = await model_provider.generate(
            [ModelMessage(role="user", content=prompt)]
        )
    except PermissionError:
        return JSONResponse(
            {"detail": "Policy denied model generation."},
            status_code=403,
        )
    return JSONResponse(
        {
            "content": result.content,
            "model": result.model,
            "provider": result.provider,
            "finish_reason": result.finish_reason,
            "usage": dict(result.usage),
        }
    )


def create_app(
    identity_resolver: IdentityResolver | None = None,
    database_path: str = "./data/example.db",
    shutdown_drain_timeout: float = 30.0,
    model_provider: ModelProvider | None = None,
    policy_engine: PolicyEngine | None = None,
    model_provider_config: Mapping[str, object] | None = None,
    auto_migrate: bool = True,
) -> Starlette:
    if (model_provider is None) != (policy_engine is None):
        raise ValueError(
            "Configure both model_provider and policy_engine to enable AI generation."
        )
    if not isinstance(auto_migrate, bool):
        raise TypeError("'auto_migrate' must be a boolean.")

    provider = SQLiteProvider()
    database_subsystem = DatabaseSubsystem(provider)
    runtime_config = {
        "xyberos": {
            "runtime": {
                "shutdown_drain_timeout_seconds": shutdown_drain_timeout,
            },
            "subsystems": {
                "database": {
                    "enabled": True,
                    "provider": provider.provider_name,
                    "config": {
                        "path": database_path,
                        "journal_mode": "WAL",
                        "busy_timeout_ms": 30_000,
                    },
                },
            },
        }
    }
    if model_provider is not None:
        runtime_config["xyberos"]["subsystems"]["ai"] = {
            "enabled": True,
            "provider": model_provider.provider_name,
            "config": dict(model_provider_config or {}),
        }
    kernel = XyberosKernel(
        runtime_config
    )
    kernel.register_provider("database", provider)
    kernel.register_subsystem("database", database_subsystem)
    if model_provider is not None and policy_engine is not None:
        kernel.register_provider("ai", model_provider)
        kernel.register_subsystem("ai", AISubsystem(model_provider))
        kernel.container.register_utility(PolicyEngine, policy_engine)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.ready = False
        await kernel.bootstrap()
        try:
            database = kernel.container.resolve(Database)
            if auto_migrate:
                await migrate_schema(database)
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            await kernel.shutdown()

    async def probe_database() -> None:
        database = kernel.container.resolve(Database)
        await database.fetch_one("SELECT 1")
        migration = await database.fetch_one(
            "SELECT version FROM xyberos_schema_migrations WHERE version = ?",
            (1,),
        )
        if migration is None:
            raise RuntimeError("Example application schema migration 1 is missing.")

    app = Starlette(
        routes=[
            *create_health_routes(kernel, probes={"database": probe_database}),
            Route("/items", list_items, methods=["GET"]),
            Route("/items", create_item, methods=["POST"]),
            Route("/items/{item_id}", get_item, methods=["GET"]),
            Route("/items/{item_id}", delete_item, methods=["DELETE"]),
            *(
                [Route("/ai/generate", generate_text, methods=["POST"])]
                if model_provider is not None
                else []
            ),
        ],
        lifespan=lifespan,
    )
    app.state.kernel = kernel
    app.add_middleware(
        XyberosContextMiddleware,
        identity_resolver=identity_resolver,
        excluded_paths=("/health/live", "/health/ready"),
    )
    app.add_middleware(KernelAdmissionMiddleware, kernel=kernel)
    return app


app = create_app()
