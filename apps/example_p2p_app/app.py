from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from xyberos.http.health import create_health_routes
from xyberos.http.middleware import (
    IdentityResolver,
    KernelAdmissionMiddleware,
    XyberosContextMiddleware,
)
from xyberos.kernel import ExecutionContextAccessor, XyberosKernel
from xyberos.providers.database import SQLiteProvider
from xyberos.providers.p2p import (
    ConfiguredPeerIdentityProvider,
    InMemoryPeerTransport,
    SQLitePeerMessageStore,
)
from xyberos.subsystems.database import Database, DatabaseSubsystem
from xyberos.subsystems.p2p import (
    OfflineMessagingService,
    P2PSubsystem,
    PeerMessageSubmissionError,
    PeerSyncError,
    TenantScopedMessagingService,
)


async def _read_json_body(request: Request) -> dict[str, object]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise TypeError("Request body must be a JSON object.")
    return body


def _normalize_sequence(value: Mapping[str, Sequence[str]] | None) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    normalized: dict[str, tuple[str, ...]] = {}
    for tenant_id, peers in value.items():
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Tenant IDs must be non-empty text.")
        peers_tuple = tuple(str(peer).strip() for peer in peers)
        if not peers_tuple or any(not peer for peer in peers_tuple):
            raise ValueError(f"Tenant '{tenant_id}' has no valid authorized peers.")
        normalized[tenant_id] = peers_tuple
    return normalized


def _serialize_message(message) -> dict[str, object]:
    return {
        "message_id": message.message_id,
        "conversation_id": message.conversation_id,
        "sender_peer_id": message.sender_peer_id,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
    }


async def _list_messages(request: Request) -> JSONResponse:
    context = ExecutionContextAccessor.get()
    tenant_id = request.path_params["tenant_id"]
    conversation_id = request.path_params["conversation_id"]
    if tenant_id != context.tenant_id:
        return JSONResponse({"detail": "Tenant mismatch."}, status_code=403)
    service = request.app.state.secure_messaging
    try:
        messages = await service.list_messages(tenant_id, conversation_id)
    except PermissionError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse({"messages": [_serialize_message(message) for message in messages]})


async def _send_message(request: Request) -> JSONResponse:
    context = ExecutionContextAccessor.get()
    tenant_id = request.path_params["tenant_id"]
    conversation_id = request.path_params["conversation_id"]
    if tenant_id != context.tenant_id:
        return JSONResponse({"detail": "Tenant mismatch."}, status_code=403)
    try:
        body = await _read_json_body(request)
    except (TypeError, ValueError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    message_text = body.get("body")
    if not isinstance(message_text, str) or not message_text.strip():
        return JSONResponse({"detail": "'body' must be non-empty text."}, status_code=400)
    service = request.app.state.secure_messaging
    try:
        message = await service.send_message(tenant_id, conversation_id, message_text)
    except PermissionError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse({"message": _serialize_message(message)}, status_code=201)


async def _sync_messages(request: Request) -> JSONResponse:
    context = ExecutionContextAccessor.get()
    tenant_id = request.path_params["tenant_id"]
    conversation_id = request.path_params["conversation_id"]
    peer_id = request.path_params["peer_id"]
    if tenant_id != context.tenant_id:
        return JSONResponse({"detail": "Tenant mismatch."}, status_code=403)
    service = request.app.state.secure_messaging
    try:
        merged = await service.synchronize(tenant_id, conversation_id, peer_id)
    except PeerMessageSubmissionError as exc:
        return JSONResponse(
            {
                "detail": str(exc),
                "peer_id": exc.peer_id,
                "merged": exc.merged_count,
                "rejected_message_ids": list(exc.rejected_message_ids),
            },
            status_code=207,
        )
    except PermissionError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except PeerSyncError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    return JSONResponse({"merged": merged, "conversation_id": conversation_id})


def create_app(
    identity_resolver: IdentityResolver | None = None,
    *,
    database_path: str = "./data/example_p2p_app.db",
    peer_id: str = "device-a",
    tenant_peer_map: Mapping[str, Sequence[str]] | None = None,
    allowed_conversations: Mapping[str, Sequence[str]] | None = None,
    auto_migrate: bool = True,
) -> Starlette:
    if identity_resolver is None:
        raise ValueError("An identity_resolver is required for the secure example app.")
    resolved_tenant_peers = _normalize_sequence(tenant_peer_map)
    resolved_conversations = {
        tenant_id: tuple(str(value).strip() for value in conversations)
        for tenant_id, conversations in (allowed_conversations or {}).items()
    }

    provider = SQLiteProvider()
    database_subsystem = DatabaseSubsystem(provider)
    kernel = XyberosKernel(
        {
            "xyberos": {
                "runtime": {"shutdown_drain_timeout_seconds": 30.0},
                "subsystems": {
                    "database": {
                        "enabled": True,
                        "provider": provider.provider_name,
                        "config": {"path": database_path},
                    },
                },
            }
        }
    )
    kernel.register_provider("database", provider)
    kernel.register_subsystem("database", database_subsystem)

    identity = ConfiguredPeerIdentityProvider()
    message_store = SQLitePeerMessageStore(provider)
    transport = InMemoryPeerTransport()
    p2p_subsystem = P2PSubsystem(identity, message_store, transport)
    kernel.register_subsystem("p2p", p2p_subsystem)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.ready = False
        await kernel.bootstrap()
        try:
            if auto_migrate:
                database = kernel.container.resolve(Database)
                await database.execute(
                    """
                    CREATE TABLE IF NOT EXISTS example_p2p_messages (
                        message_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        peer_id TEXT NOT NULL,
                        body TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            await p2p_subsystem.initialize(
                {
                    "identity": {"peer_id": peer_id},
                    "message_store": {},
                    "transport": {},
                },
                kernel.container,
            )
            app.state.secure_messaging = TenantScopedMessagingService(
                kernel.container.resolve(OfflineMessagingService),
                resolved_tenant_peers,
                resolved_conversations,
            )
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            await p2p_subsystem.shutdown()
            await message_store.close()
            await identity.close()
            await transport.close()
            await provider.close()
            await kernel.shutdown()

    app = Starlette(
        routes=[
            *create_health_routes(
                kernel,
                probes={
                    "database": lambda: None,
                },
            ),
            Route(
                "/v1/tenants/{tenant_id}/conversations/{conversation_id}/messages",
                _list_messages,
                methods=["GET"],
            ),
            Route(
                "/v1/tenants/{tenant_id}/conversations/{conversation_id}/messages",
                _send_message,
                methods=["POST"],
            ),
            Route(
                "/v1/tenants/{tenant_id}/conversations/{conversation_id}/sync/{peer_id}",
                _sync_messages,
                methods=["POST"],
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


app = create_app(
    identity_resolver=lambda request: None,
    peer_id="device-a",
    tenant_peer_map={"tenant-a": ("device-b",), "tenant-b": ("device-c",)},
    allowed_conversations={"tenant-a": ("conversation-1",), "tenant-b": ("conversation-2",)},
)
